# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

import functools
import os
import re
from typing import List, Optional

from google.protobuf import json_format

from PB.chromite.api import sdk as sdk_pb2
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)
from PB.recipes.chromeos import build_sdk as build_sdk_pb2
from PB.recipe_modules.chromeos.pupr_local_uprev import (pupr_local_uprev as
                                                         pupr_local_uprev_pb2)
from RECIPE_MODULES.chromeos.cros_sdk import api as cros_sdk_api

from recipe_engine import config_types
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'easy',
    'key_value_store',
    'src_state',
    'util',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = build_sdk_pb2.BuildSDKProperties

# SDK_BUILD_TARGET is the name of the build target to build SDK packages for.
SDK_BUILD_TARGET = 'amd64-host'
# SDK_ARCH is the architecture of the SDK_BUILD_TARGET.
SDK_ARCH = 'amd64'

# LLVM_NEXT_USE_FLAG is the name of the USE flag for llvm-next builds.
LLVM_NEXT_USE_FLAG = 'llvm-next'

# Google storage buckets for uploads: i.e., what comes after "gs://"
SDK_BUCKET = 'chromiumos-sdk'
PREBUILTS_BUCKET = 'chromeos-prebuilt'
THROW_AWAY_BUCKET = 'chromeos-throw-away-bucket'


def RunSteps(api: recipe_api.RecipeApi,
             properties: build_sdk_pb2.BuildSDKProperties):
  BuildSDKRun(api, properties).run()


class BuildSDKRun:
  """Class to encapsulate a single run of the SDK builder."""

  def __init__(self, api: recipe_api.RecipeApi,
               properties: build_sdk_pb2.BuildSDKProperties):
    """Initialize the builder run."""
    self.m = api
    self.properties = properties

    # Paths of built files. These will be set after build API calls.
    self._sdk_tarball_path: Optional[config_types.Path] = None
    self._sdk_manifest_path: Optional[config_types.Path] = None
    self._toolchain_tarball_paths: Optional[List[config_types.Path]] = None

    self.m.easy.set_properties_step(version=self.version)

  @functools.cached_property
  def version(self) -> str:
    """Return the SDK version created by this build.

    Typically, SDK builds are versioned according to the build start time.
    For example, '2023.03.14.159265'.
    However, this can be overridden by input properties.
    """
    if self.properties.version:
      return self.properties.version
    return self.m.buildbucket.build.start_time.ToDatetime().strftime(
        '%Y.%m.%d.%H%M%S')

  @functools.cached_property
  def _toolchain_tarball_dir(self) -> str:
    """Return the remote dir for toolchain tarballs, relative to SDK_BUCKET.

    Typically toolchain tarballs go into a directory timestamped as 'YYYY/MM'.
    For example: gs://chromiumos-sdk/2023/03/, for a build from March 2023.

    Returns:
      The Google Storage folder, relative to SDK_BUCKET, with a trailing slash.
      For example, '2023/03/'.
    """
    return self.m.buildbucket.build.start_time.ToDatetime().strftime('%Y/%m/')

  @functools.cached_property
  def _toolchain_tarball_template(self) -> str:
    """Return the remote toolchain tarball template, relative to SDK_BUCKET.

    This eventually gets sent into the source-controlled sdk_version.conf, as
    TC_PATH. Chromite consumes the value and %-formats it with the named string
    "target" representing a build target architecture. Thus, the template must
    include the string literal "%(target)s".

    Returns:
      A template for toolchain tarballs, relative to SDK_BUCKET. FOr example,
      '2023/03/%(target)s-2023.03.14.159265.tar.xz'.
    """
    return os.path.join(self._toolchain_tarball_dir,
                        f'%(target)s-{self.version}.tar.xz')

  def run(self):
    """Run the main logic for this builder."""
    with self.m.build_menu.configure_builder(missing_ok=True), \
        self.m.build_menu.setup_workspace_and_chroot(bootstrap_chroot=True,
                                                     replace=True,
                                                     update_chroot=False):
      self._build_sdk_packages()
      self._build_toolchain()
      self._create_sdk_tarball()
      self._create_sdk_manifest()
      self._upload_prebuilts()
      self._upload_sdk_tarball_and_manifest()
      self._update_gs_latest_file()
      if self.properties.launch_pupr:
        self._schedule_uprev()

  def _build_sdk_packages(self) -> None:
    """Build all packages for the SDK build target."""
    request = sdk_pb2.BuildPrebuiltsRequest(chroot=self.m.cros_sdk.chroot)
    self.m.cros_build_api.SdkService.BuildPrebuilts(request)

  def _build_toolchain(self) -> None:
    """Build cross-compiling toolchains for the SDK.

    This method sets the self._toolchain_tarball_paths attribute to a list
    of Paths of the generated toolchain tarballs.
    """
    result_path: config_types.Path = self.m.path.mkdtemp()
    request = sdk_pb2.BuildSdkToolchainRequest(
        chroot=self.m.cros_sdk.chroot,
        result_path=common_pb2.ResultPath(
            path=common_pb2.Path(
                path=self.m.path.abspath(result_path),
                location=common_pb2.Path.Location.OUTSIDE,
            )),
    )
    if self.properties.use_llvm_next:
      request.use_flags.add(flag=LLVM_NEXT_USE_FLAG)
    response = self.m.cros_build_api.SdkService.BuildSdkToolchain(request)
    self._toolchain_tarball_paths = []
    for generated_file in response.generated_files:
      path = self.m.util.proto_path_to_recipes_path(generated_file)
      self._toolchain_tarball_paths.append(path)
      self.m.path.mock_add_file(path)

  def _create_sdk_tarball(self) -> None:
    """Create a tarball containing a previously built SDK.

    This method sets the self._sdk_tarball_path attribute to the Path of the
    generated tarball.
    """
    request = sdk_pb2.BuildSdkTarballRequest(chroot=self.m.cros_sdk.chroot)
    response = self.m.cros_build_api.SdkService.BuildSdkTarball(request)
    self._sdk_tarball_path = self.m.util.proto_path_to_recipes_path(
        response.sdk_tarball_path)
    self.m.path.mock_add_file(self._sdk_tarball_path)

  def _create_sdk_manifest(self) -> None:
    """Create a manifest file showing the ebuilds in an SDK.

    This method sets the self._sdk_manifest_path attribute to the Path of the
    generated manifest.
    """
    assert self._sdk_tarball_path is not None
    request = sdk_pb2.CreateManifestFromSdkRequest(
        chroot=self.m.cros_sdk.chroot,
        sdk_path=common_pb2.Path(
            path=f'/build/{SDK_BUILD_TARGET}',
            location=common_pb2.Path.INSIDE,
        ),
        dest_dir=common_pb2.Path(
            path=str(self.m.workspace_util.workspace_path),
            location=common_pb2.Path.OUTSIDE,
        ),
    )
    response = self.m.cros_build_api.SdkService.CreateManifestFromSdk(request)
    self._sdk_manifest_path = self.m.util.proto_path_to_recipes_path(
        response.manifest_path)
    self.m.path.mock_add_file(self._sdk_manifest_path)

  def _upload_prebuilts(self) -> None:
    """Upload binaries generated by this build."""
    with self.m.step.nest('upload prebuilts'):
      self._upload_host_prebuilts()
      self._upload_target_prebuilts()
      self._upload_toolchain_prebuilts()

  def _upload_host_prebuilts(self) -> None:
    """Upload host binaries to GS://.

    The destination folder typically looks like:
      gs://chromeos-prebuilt/host/amd64/amd64-host/chroot-${version}/packages/
    where ${version} is the SDK version (declared elsewhere in this recipe).

    Raises:
      AssertionError: If toolchain tarballs have not been built yet.
    """
    with self.m.step.nest('upload host prebuilts'):
      source_dir = self.m.cros_sdk.chroot_path.join('var', 'lib', 'portage',
                                                    'pkgs')
      dest_bucket = self._pick_bucket(PREBUILTS_BUCKET)
      dest_path = os.path.join('host', SDK_ARCH, SDK_BUILD_TARGET,
                               f'chroot-{self.version}', 'packages')
      self.m.path.mock_add_directory(source_dir)
      self._gsutil_upload(source_dir, dest_bucket, dest_path)

  def _upload_target_prebuilts(self) -> None:
    """Upload binaries for the amd64-host build target to GS://.

    The destination folder typically looks like:
      gs://chromeos-prebuilt/board/amd64-host/chroot-${version}/packages/
    where ${version} is the SDK version (declared elsewhere in this recipe).

    Raises:
      AssertionError: If toolchain tarballs have not been built yet.
    """
    with self.m.step.nest('upload target prebuilts'):
      source_dir = self.m.cros_sdk.chroot_path.join('build', SDK_BUILD_TARGET,
                                                    'packages')
      dest_bucket = self._pick_bucket(PREBUILTS_BUCKET)
      dest_path = os.path.join('board', SDK_BUILD_TARGET,
                               f'chroot-{self.version}', 'packages')
      self.m.path.mock_add_directory(source_dir)
      self._gsutil_upload(source_dir, dest_bucket, dest_path)

  def _upload_toolchain_prebuilts(self) -> None:
    """Upload toolchain prebuilt tarballs to Google Storage.

    Raises:
      AssertionError: If toolchain tarballs have not been built yet.
    """
    with self.m.step.nest('upload sdk toolchain tarballs'):
      assert self._toolchain_tarball_paths is not None
      for local_path in self._toolchain_tarball_paths:
        self._upload_one_toolchain_prebuilt(local_path)

  def _upload_one_toolchain_prebuilt(self,
                                     source_path: config_types.Path) -> None:
    """Upload a single toolchain prebuilt tarball to Google Storage.

    The destination path typically looks like:
      gs://chromiumos-sdk/${YEAR}/${MONTH}/${TARGET}-${VERSION}.tar.xz
    where:
      ${YEAR} is the current four-digit year (ex. 2023).
      ${MONTH} is the current four-digit month (ex. 03).
      ${TARGET} is the target architecture (ex. aarch64-cros-linux-gnu).
      ${VERSION} is the SDK version (ex. 2023.03.14.159265).

    Args:
      source_path: The local path to the toolchain file.
    """
    basename = self.m.path.basename(source_path)
    with self.m.step.nest(f'upload {basename}'):
      dest_bucket = self._pick_bucket(SDK_BUCKET)
      dest_path = os.path.join(self._toolchain_tarball_dir, basename)
      self._gsutil_upload(source_path, dest_bucket, dest_path)

  def _upload_sdk_tarball_and_manifest(self) -> None:
    """Upload the SDK tarball, and corresponding manifest, to GS://.

    The destination URI for the SDK tarball typically looks like:
      gs://chromiumos-sdk/cros-sdk-${version}.tar.xz
    where ${version} is the SDK version (declared elsewhere in this recipe).

    The destination URI for the manifest file is typically the same as the
    tarball's destination, but with `.Manifest` appended to the basename.

    Raises:
      AssertionError: If the SDK tarball or manifest has not been built yet.
    """
    with self.m.step.nest('upload sdk tarball and manifest'):
      dest_bucket = self._pick_bucket(SDK_BUCKET)
      with self.m.step.nest('upload sdk tarball'):
        assert self._sdk_tarball_path is not None
        tarball_dest_path = f'cros-sdk-{self.version}.tar.xz'
        self._gsutil_upload(self._sdk_tarball_path, dest_bucket,
                            tarball_dest_path)
      with self.m.step.nest('upload sdk manifest'):
        assert self._sdk_manifest_path is not None
        manifest_dest_path = f'{tarball_dest_path}.Manifest'
        self._gsutil_upload(self._sdk_manifest_path, dest_bucket,
                            manifest_dest_path)

  def _update_gs_latest_file(self) -> None:
    """Update the GS:// latest SDK file to point to the newly built SDK."""
    with self.m.step.nest('update gs:// latest file') as presentation:
      old_contents = self._read_existing_gs_latest_file()
      new_contents = self.m.key_value_store.update_one_value(
          old_contents, 'LATEST_SDK_UPREV_TARGET', self.version, True)
      tempfile = self.m.path.mkstemp()
      self.m.file.write_text('write local file to upload', tempfile,
                             new_contents)
      dest_bucket = self._pick_bucket(SDK_BUCKET)
      self._gsutil_upload(tempfile, dest_bucket, 'cros-sdk-latest.conf')
      presentation.properties['new_LATEST_SDK_UPREV_TARGET'] = self.version

  def _read_existing_gs_latest_file(self) -> str:
    """Read, log, and return the existing latest SDK file on GS://.

    Returns:
      The raw contents of the remote file.
    """
    with self.m.step.nest('read existing latest file') as presentation:
      contents = self.m.cros_sdk.read_remote_latest_sdk_file()
      presentation.logs['existing file contents'] = contents
      contents_dict = self.m.key_value_store.parse_contents(
          contents, source=cros_sdk_api.REMOTE_LATEST_SDK_URI)
      presentation.properties['old_LATEST_SDK'] = contents_dict.get(
          'LATEST_SDK', "None")
      presentation.properties[
          'old_LATEST_SDK_UPREV_TARGET'] = contents_dict.get(
              'LATEST_SDK_UPREV_TARGET', "None")
    return contents

  def _pick_bucket(self, prod_bucket: str) -> str:
    """Return prod_bucket or THROW_AWAY_BUCKET based on staging status.

    The staging builder deliberately doesn't have write access to most buckets.
    Thus, many upload steps should upload to THROW_AWAY_BUCKET in staging.

    However, we shouldn't apply this 100% of the time, because we do want the
    staging builder to upload to gs://chromeos-image-archive/.

    Args:
      prod_bucket: The bucket to return if this is a prod builder.

    Returns:
      A bucket name (without the gs:// prefix).
    """
    return THROW_AWAY_BUCKET if self.m.build_menu.is_staging else prod_bucket

  def _gsutil_upload(self, source_path: config_types.Path, dest_bucket: str,
                     dest_path: str) -> None:
    """Wrapper around self.m.gsutil.upload() with some common functionality.

    Fails if the source path is not present on the filesystem.

    Always uploads directories with -r for recursive mode, and multithreaded.

    Always uploads with the `public-read` canned ACL, since SDK artifacts can
    be used by anybody.

    If the upload_to_staging_dir property is True, then the destination dir
    will have "staging/" prepended.

    Args:
      source_path: Local filepath to upload.
      dest_bucket: The Google Storage bucket to upload to (without "gs://").
      dest_path: The filepath within dest_bucket to upload to.

    Raises:
      InfraFailure: If the local filepath is not present on the filesystem.
    """
    # It's easiest to mock the paths into existence as soon as the BAPI returns
    # them. So currently I don't have a great way to test the case where we want
    # to upload a path that doesn't exist.
    if not self.m.path.exists(source_path):  # pragma: nocover
      raise recipe_api.InfraFailure(
          f'Upload source "{source_path}" not found locally.')
    args = ['-a', 'public-read']
    if self.m.path.isdir(source_path):
      args.append('-r')
      multithreaded = True
    else:
      multithreaded = False
    if self.properties.upload_to_staging_dir:
      dest_path = os.path.join('staging', dest_path)
    self.m.gsutil.upload(
        str(source_path), dest_bucket, dest_path, args=args,
        multithreaded=multithreaded)

  def _schedule_uprev(self) -> None:
    """Trigger a PUpr build to uprev to the newly-built SDK.

    The PUpr build should be staging if this build is staging, and prod if this
    build is prod.

    PUpr uses GitilesTriggers to pick a branch policy, because originally all
    uprevs were triggered by gitiles changes. Luckily, it provides a property
    for spoofing GitilesTriggers.
    """
    if self.m.build_menu.is_staging:
      bucket, builder = 'staging', 'staging-chromiumos-sdk-pupr-generator'
    else:
      bucket, builder = 'pupr', 'chromiumos-sdk-pupr-generator'
    request = self.m.buildbucket.schedule_request(
        builder=builder,
        bucket=bucket,
        properties={
            '$chromeos/pupr_local_uprev':
                json_format.MessageToDict(
                    pupr_local_uprev_pb2.PuprLocalUprevProperties(
                        sdk_uprev_spec=pupr_local_uprev_pb2.SdkUprevSpec(
                            sdk_version=self.version,
                            toolchain_template=self._toolchain_tarball_template,
                        ))),
            # PUpr uses its GitilesTriggers to pick a branch policy, because
            # PUpr was originally always triggered by gitiles changes. Today, it
            # allows spoofing GitilesTriggers via input properties.
            # The ref is useful because it tells PUpr which branch to upload to.
            # However, the repo and revision should be unnecessary.
            'triggers': [
                json_format.MessageToDict(
                    triggers_pb2.Trigger(
                        gitiles=triggers_pb2.GitilesTrigger(
                            ref="refs/heads/main")))
            ],
        },
        can_outlive_parent=True,
    )
    self.m.buildbucket.schedule([request], step_name='schedule uprev')


def GenTests(api: recipe_test_api.RecipeTestApi):
  # RE_GSUTIL is a regex that looks for a path ending in 'gsutil.py'.
  # This is useful for post_process.StepCommandContains, since we don't really
  # care about the full path to gsutil.py.
  RE_GSUTIL = re.compile(r'gsutil\.py$')

  # DEFAULT_VERSION is a parsing of the buildbucket API's default start_time.
  DEFAULT_VERSION = "1970.01.01.000000"

  yield api.test(
      'basic',
      api.properties(launch_pupr=True),
      api.post_check(post_process.PropertyEquals, 'version', DEFAULT_VERSION),
      # Make sure we're not updating the chroot, since we need to ensure that
      # all host packages can be built using the bootstrap SDK version.
      api.post_check(post_process.DoesNotRun, 'update sdk'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildPrebuilts'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkToolchain'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkTarball'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/CreateManifestFromSdk'),
      # Check that all upload steps actually perform gsutil commands.
      api.post_check(post_process.StepCommandContains,
                     'upload prebuilts.upload host prebuilts.gsutil upload',
                     [RE_GSUTIL]),
      api.post_check(post_process.StepCommandContains,
                     'upload prebuilts.upload target prebuilts.gsutil upload',
                     [RE_GSUTIL]),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload sdk toolchain tarballs.upload foo.tar.xz.gsutil upload',
          [RE_GSUTIL]),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload sdk toolchain tarballs.upload bar.tar.xz.gsutil upload',
          [RE_GSUTIL]),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload',
          [RE_GSUTIL]),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk manifest.gsutil upload',
          [RE_GSUTIL]),
      # For at least one of the gsutil upload commands (don't need all of them),
      # check that we're not uploading to a staging/ path.
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload', [
              RE_GSUTIL, '----', 'cp', '-a', 'public-read',
              '[CLEANUP]/chromiumos_workspace/built-sdk.tar.xz',
              'gs://chromiumos-sdk/cros-sdk-1970.01.01.000000.tar.xz'
          ]),
      # Check the processing of the upstream latest file.
      api.post_check(
          post_process.PropertyEquals,
          "old_LATEST_SDK",
          "2023.03.13.222421",
      ),
      api.post_check(
          post_process.PropertyEquals,
          "old_LATEST_SDK_UPREV_TARGET",
          "2023.03.14.159265",
      ),
      api.post_check(
          post_process.PropertyEquals,
          "new_LATEST_SDK_UPREV_TARGET",
          DEFAULT_VERSION,
      ),
      # Prod builder should run prod PUpr.
      api.post_check(post_process.MustRun, 'schedule uprev'),
      api.post_check(post_process.LogContains, 'schedule uprev', 'request', [
          r'"bucket": "pupr"',
          r'"builder": "chromiumos-sdk-pupr-generator"',
          r'"sdkVersion": "1970.01.01.000000"',
          r'"toolchainTemplate": "1970/01/%(target)s-1970.01.01.000000.tar.xz"',
      ]),
  )

  yield api.test(
      'llvm-next',
      api.properties(use_llvm_next=True),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkToolchain'),
      api.post_check(post_process.LogContains,
                     'call chromite.api.SdkService/BuildSdkToolchain',
                     'request', [f'"flag": "{LLVM_NEXT_USE_FLAG}"']),
      # llvm-next builder should not run PUpr.
      api.post_check(post_process.DoesNotRun, 'schedule uprev'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.build_menu.test(
      'staging',
      api.properties(launch_pupr=True),
      # These steps should all upload to THROW_AWAY_BUCKET on staging builders.
      # However, they should not upload to the /staging/ subdir.
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload host prebuilts.gsutil upload', [
              'gs://chromeos-throw-away-bucket/host/amd64/amd64-host/chroot-1970.01.01.000000/packages'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload target prebuilts.gsutil upload', [
              'gs://chromeos-throw-away-bucket/board/amd64-host/chroot-1970.01.01.000000/packages'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload sdk toolchain tarballs.upload foo.tar.xz.gsutil upload',
          ['gs://chromeos-throw-away-bucket/1970/01/foo.tar.xz']),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload sdk toolchain tarballs.upload bar.tar.xz.gsutil upload',
          ['gs://chromeos-throw-away-bucket/1970/01/bar.tar.xz']),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload',
          ['gs://chromeos-throw-away-bucket/cros-sdk-1970.01.01.000000.tar.xz'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk manifest.gsutil upload', [
              'gs://chromeos-throw-away-bucket/cros-sdk-1970.01.01.000000.tar.xz.Manifest'
          ]),
      # Staging builder should launch the staging PUpr.
      api.post_check(post_process.MustRun, 'schedule uprev'),
      api.post_check(post_process.LogContains, 'schedule uprev', 'request',
                     (r'"bucket": "staging"',
                      r'"builder": "staging-chromiumos-sdk-pupr-generator"')),
      api.post_process(post_process.DropExpectation),
      builder='staging-chromiumos-sdk',
      bucket='staging',
  )

  yield api.test(
      'upload-to-staging-dir',
      api.properties(upload_to_staging_dir=True),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload', [
              RE_GSUTIL, '----', 'cp', '-a', 'public-read',
              "[CLEANUP]/chromiumos_workspace/built-sdk.tar.xz",
              "gs://chromiumos-sdk/staging/cros-sdk-1970.01.01.000000.tar.xz"
          ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.build_menu.test(
      'staging-upload-to-staging-dir',
      api.properties(upload_to_staging_dir=True),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload', [
              RE_GSUTIL, '----', 'cp', '-a', 'public-read',
              '[CLEANUP]/chromiumos_workspace/built-sdk.tar.xz',
              'gs://chromeos-throw-away-bucket/staging/cros-sdk-1970.01.01.000000.tar.xz'
          ]),
      api.post_process(post_process.DropExpectation),
      builder='staging-chromiumos-sdk',
      bucket='staging',
  )

  yield api.build_menu.test(
      'declare-version-in-properties',
      api.properties(version='my-cool-version'),
      api.post_check(post_process.PropertyEquals, 'version', 'my-cool-version'),
      api.post_process(post_process.DropExpectation),
  )
