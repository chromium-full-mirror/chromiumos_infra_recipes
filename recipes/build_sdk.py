# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

import os
import re
from typing import List, Optional

from PB.chromite.api.sdk import BuildPrebuiltsRequest
from PB.chromite.api.sdk import BuildSdkTarballRequest
from PB.chromite.api.sdk import BuildSdkToolchainRequest
from PB.chromite.api.sdk import CreateManifestFromSdkRequest
from PB.chromiumos import common as common_pb2
from PB.recipes.chromeos.build_sdk import BuildSDKProperties

from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'easy',
    'key_value_store',
    'src_state',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildSDKProperties

# SDK_BUILD_TARGET is the name of the build target to build SDK packages for.
SDK_BUILD_TARGET = 'amd64-host'
# SDK_ARCH is the architecture of the SDK_BUILD_TARGET.
SDK_ARCH = 'amd64'

# LLVM_NEXT_USE_FLAG is the name of the USE flag for llvm-next builds.
LLVM_NEXT_USE_FLAG = 'llvm-next'

# Google storage buckets for uploads: i.e., what comes after "gs://"
SDK_BUCKET = 'chromiumos-sdk'
PREBUILTS_BUCKET = 'chromeos-prebuilt'


def RunSteps(api: RecipeApi, properties: BuildSDKProperties):
  BuildSDKRun(api, properties).run()


class BuildSDKRun:
  """Class to encapsulate a single run of the SDK builder."""

  def __init__(self, api: RecipeApi, properties: BuildSDKProperties):
    """Initialize the builder run."""
    self.m = api
    self.properties = properties
    self._sdk_tarball_path: Optional[Path] = None
    self._sdk_manifest_path: Optional[Path] = None
    self._toolchain_tarball_paths: Optional[List[Path]] = None
    self._version = properties.version or \
        self.m.buildbucket.build.start_time.ToDatetime().strftime('%Y.%m.%d.%H%M%S')
    self.m.easy.set_properties_step(version=self._version)

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

  @property
  def _skip_uploads(self):
    """Whether this builder should skip uploading to GS://."""
    return self.m.build_menu.is_staging and not self.properties.upload_to_staging_dir

  def _build_sdk_packages(self) -> None:
    """Build all packages for the SDK build target."""
    request = BuildPrebuiltsRequest(chroot=self.m.cros_sdk.chroot)
    self.m.cros_build_api.SdkService.BuildPrebuilts(request)

  def _build_toolchain(self) -> None:
    """Build cross-compiling toolchains for the SDK.

    This method sets the self._toolchain_tarball_paths attribute to a list
    of Paths of the generated toolchain tarballs.
    """
    request = BuildSdkToolchainRequest(chroot=self.m.cros_sdk.chroot)
    if self.properties.use_llvm_next:
      request.use_flags.add(flag=LLVM_NEXT_USE_FLAG)
    response = self.m.cros_build_api.SdkService.BuildSdkToolchain(request)
    self._toolchain_tarball_paths = []
    for generated_file in response.generated_files:
      path = self._proto_path_to_recipes_path(generated_file)
      self._toolchain_tarball_paths.append(path)
      self.m.path.mock_add_file(path)

  def _create_sdk_tarball(self) -> None:
    """Create a tarball containing a previously built SDK.

    This method sets the self._sdk_tarball_path attribute to the Path of the
    generated tarball.
    """
    request = BuildSdkTarballRequest(chroot=self.m.cros_sdk.chroot)
    response = self.m.cros_build_api.SdkService.BuildSdkTarball(request)
    self._sdk_tarball_path = self._proto_path_to_recipes_path(
        response.sdk_tarball_path)
    self.m.path.mock_add_file(self._sdk_tarball_path)

  def _create_sdk_manifest(self) -> None:
    """Create a manifest file showing the ebuilds in an SDK.

    This method sets the self._sdk_manifest_path attribute to the Path of the
    generated manifest.
    """
    assert self._sdk_tarball_path is not None
    request = CreateManifestFromSdkRequest(
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
    self._sdk_manifest_path = self._proto_path_to_recipes_path(
        response.manifest_path)
    self.m.path.mock_add_file(self._sdk_manifest_path)

  def _upload_prebuilts(self) -> None:
    """Upload binaries generated by this build."""
    with self.m.step.nest('upload prebuilts'):
      self._upload_host_prebuilts()
      self._upload_target_prebuilts()
      self._upload_packages_index()
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
      dest_path = os.path.join('host', SDK_ARCH, SDK_BUILD_TARGET,
                               f'chroot-{self._version}', 'packages')
      self.m.path.mock_add_directory(source_dir)
      self._gsutil_upload(source_dir, PREBUILTS_BUCKET, dest_path)

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
      dest_path = os.path.join('board', SDK_BUILD_TARGET,
                               f'chroot-{self._version}', 'packages')
      self.m.path.mock_add_directory(source_dir)
      self._gsutil_upload(source_dir, PREBUILTS_BUCKET, dest_path)

  def _upload_packages_index(self) -> None:
    """Upload the packages index file to Google Storage.

    The destination URI typically looks like:
      gs://chromeos-prebuilt/board/amd64-host/chroot-{version}/packages/Packages
    where ${version} is the SDK version (declared elsewhere in this recipe).

    TODO(b/270142110): Implement this.
    """

  def _upload_toolchain_prebuilts(self) -> None:
    """Upload toolchain prebuilt tarballs to GS://.

    The destination folder typically looks like:
      gs://chromiumos-sdk/YYYY/MM
    where YYYY is the current year and MM is the current month.
    For example, gs://chromiumos-sdk/1970/01/**.tar.xz

    Raises:
      AssertionError: If toolchain tarballs have not been built yet.
    """
    with self.m.step.nest('upload sdk toolchain tarballs'):
      assert self._toolchain_tarball_paths is not None
      for source_path in self._toolchain_tarball_paths:
        self._upload_one_toolchain_prebuilt(source_path)

  def _upload_one_toolchain_prebuilt(self, source_path: Path) -> None:
    """Upload a single toolchain prebuilt tarball to GS://.

    The destination folder typically looks like:
      gs://chromiumos-sdk/YYYY/MM
    where YYYY is the current year and MM is the current month.
    For example, gs://chromiumos-sdk/1970/01/**.tar.xz

    Args:
      source_path: The local path to the toolchain file.
    """
    basename = self.m.path.basename(source_path)
    with self.m.step.nest(f'upload {basename}'):
      dest_path = os.path.join(self.m.time.utcnow().strftime('%Y/%m'), basename)
      self._gsutil_upload(source_path, SDK_BUCKET, dest_path)

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
      with self.m.step.nest('upload sdk tarball'):
        assert self._sdk_tarball_path is not None
        tarball_dest_path = f'cros-sdk-{self._version}.tar.xz'
        self._gsutil_upload(self._sdk_tarball_path, SDK_BUCKET,
                            tarball_dest_path)
      with self.m.step.nest('upload sdk manifest'):
        assert self._sdk_manifest_path is not None
        manifest_dest_path = f'{tarball_dest_path}.Manifest'
        self._gsutil_upload(self._sdk_manifest_path, SDK_BUCKET,
                            manifest_dest_path)

  def _update_gs_latest_file(self) -> None:
    """Update the GS:// latest SDK file to point to the newly built SDK."""
    with self.m.step.nest('update gs:// latest file') as presentation:
      old_contents = self._read_existing_gs_latest_file()
      new_contents = self.m.key_value_store.update_one_value(
          old_contents, 'LATEST_SDK_UPREV_TARGET', self._version, True)
      tempfile = self.m.path.mkstemp()
      self.m.file.write_text('write local file to upload', tempfile,
                             new_contents)
      self._gsutil_upload(tempfile, SDK_BUCKET, 'cros-sdk-latest.conf')
      presentation.properties['new_LATEST_SDK_UPREV_TARGET'] = self._version

  def _read_existing_gs_latest_file(self) -> str:
    """Read, log, and return the existing latest SDK file on GS://.

    Returns:
      The raw contents of the existing file.
    """
    with self.m.step.nest('read existing latest file') as presentation:
      uri = f'gs://{SDK_BUCKET}/cros-sdk-latest.conf'
      contents = self.m.gsutil.cat(
          uri, stdout=self.m.raw_io.output(),
          step_test_data=lambda: self.m.raw_io.test_api.stream_output(
              '# The most recent SDK that is tested and ready for use.\n'
              'LATEST_SDK="2023.03.13.222421"\n'
              '\n'
              '# The most recently built version. New uprev attempts should target this.\n'
              '# Warning: This version may not be tested yet.\n'
              'LATEST_SDK_UPREV_TARGET="2023.03.14.159265"')).stdout.decode()
      presentation.logs['existing file contents'] = contents
      contents_dict = self.m.key_value_store.parse_contents(
          contents, source='remote latest file')
      presentation.properties['old_LATEST_SDK'] = contents_dict.get(
          'LATEST_SDK', "None")
      presentation.properties[
          'old_LATEST_SDK_UPREV_TARGET'] = contents_dict.get(
              'LATEST_SDK_UPREV_TARGET', "None")
    return contents

  def _gsutil_upload(self, source_path: Path, dest_bucket: str,
                     dest_path: str) -> None:
    """Wrapper around self.m.gsutil.upload() with some common functionality.

    Fails if the source path is not present on the filesystem.

    Always uploads directories with -r for recursive mode, and multithreaded.

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
      raise InfraFailure(f'Upload source "{source_path}" not found locally.')
    if self.m.path.isdir(source_path):
      args = ['-r']
      multithreaded = True
    else:
      args = []
      multithreaded = False
    if self.properties.upload_to_staging_dir:
      dest_path = os.path.join('staging', dest_path)
    self.m.gsutil.upload(
        str(source_path), dest_bucket, dest_path, args=args,
        multithreaded=multithreaded, dry_run=self._skip_uploads)

  def _proto_path_to_recipes_path(self, pb2_path: common_pb2.Path) -> Path:
    """Return a config_types.Path equivalent to the common_pb2.Path.

    Args:
      pb2_path: A Path, as might be returned by the build API. Must be absolute,
        and location must be specified as either INSIDE or OUTSIDE.

    Raises:
      ValueError: If pb2_path.location is OUTSIDE, but pb2_path.path is not
        relative to one of the recipe anchor points. See
        recipe_deps/recipe_engine/recipe_modules/path/api.py for more info about
        those anchor points.
      AssertionError: If pb2_path.location is INSIDE, and pb2_path.path is not
        relative to '/'.
      InfraFailure: If pb2_path.location is not specified as either INSIDE or
        OUTSIDE.
    """
    if pb2_path.location == common_pb2.Path.Location.OUTSIDE:
      return self.m.path.abs_to_path(pb2_path.path)
    if pb2_path.location == common_pb2.Path.Location.INSIDE:
      assert pb2_path.path.startswith('/'), \
        f'Cannot convert inside path not relative to "/": {pb2_path}'
      relative_to_chroot = pb2_path.path.lstrip('/')
      path_parts = relative_to_chroot.split('/')
      return self.m.cros_sdk.chroot_path.join(*path_parts)
    raise InfraFailure(
        f'Cannot process path with unspecified location: {pb2_path}')


def GenTests(api: RecipeTestApi):
  # RE_GSUTIL is a regex that looks for a path ending in 'gsutil.py'.
  # This is useful for post_process.StepCommandContains, since we don't really
  # care about the full path to gsutil.py.
  RE_GSUTIL = re.compile(r'gsutil\.py$')

  # DEFAULT_VERSION is a parsing of the buildbucket API's default start_time.
  DEFAULT_VERSION = "1970.01.01.000000"

  yield api.test(
      'basic',
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
              RE_GSUTIL, '----', 'cp',
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
      status='SUCCESS')

  yield api.test(
      'llvm-next',
      api.properties(use_llvm_next=True),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkToolchain'),
      api.post_check(post_process.LogContains,
                     'call chromite.api.SdkService/BuildSdkToolchain',
                     'request', [f'"flag": "{LLVM_NEXT_USE_FLAG}"']),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  yield api.test(
      'fail-if-unspecified-location',
      api.cros_build_api.set_api_return(
          '',
          'SdkService/BuildSdkTarball',
          '{"sdk_tarball_path": {"path": "/path/to/sdk.tar.xz"}}',
      ),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.build_menu.test(
      'staging-does-not-upload',
      api.post_check(post_process.StepCommandEmpty,
                     'upload prebuilts.upload host prebuilts.gsutil upload'),
      api.post_check(post_process.StepCommandEmpty,
                     'upload prebuilts.upload target prebuilts.gsutil upload'),
      api.post_check(
          post_process.StepCommandEmpty,
          'upload prebuilts.upload sdk toolchain tarballs.upload foo.tar.xz.gsutil upload'
      ),
      api.post_check(
          post_process.StepCommandEmpty,
          'upload prebuilts.upload sdk toolchain tarballs.upload bar.tar.xz.gsutil upload'
      ),
      api.post_check(
          post_process.StepCommandEmpty,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload'),
      api.post_check(
          post_process.StepCommandEmpty,
          'upload sdk tarball and manifest.upload sdk manifest.gsutil upload'),
      builder='staging-chromiumos-sdk',
      bucket='staging',
      status='SUCCESS',
  )

  yield api.test(
      'upload-to-staging-dir',
      api.properties(upload_to_staging_dir=True),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload', [
              RE_GSUTIL, '----', 'cp',
              "[CLEANUP]/chromiumos_workspace/built-sdk.tar.xz",
              "gs://chromiumos-sdk/staging/cros-sdk-1970.01.01.000000.tar.xz"
          ]),
  )

  yield api.build_menu.test(
      'staging-upload-to-staging-dir',
      api.properties(upload_to_staging_dir=True),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload', [
              RE_GSUTIL, '----', 'cp',
              '[CLEANUP]/chromiumos_workspace/built-sdk.tar.xz',
              'gs://chromiumos-sdk/staging/cros-sdk-1970.01.01.000000.tar.xz'
          ]),
      builder='staging-chromiumos-sdk',
      bucket='staging',
      status='SUCCESS',
  )
