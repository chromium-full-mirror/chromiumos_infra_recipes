# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

import contextlib
import dataclasses
import functools
import os
import re
from typing import Dict, Generator, List, Optional

from google.protobuf import json_format

from PB.chromite.api import sdk as sdk_pb2
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)
from PB.recipes.chromeos import build_sdk as build_sdk_pb2
from PB.recipes.chromeos import generator as generator_pb2
from PB.recipe_engine import result as result_pb2
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

# Google storage buckets for uploads: i.e., what comes after 'gs://'.
# Both of these are for the production builder. The staging builder uploads to
# staging buckets, which are identical but with a 'staging-' prefix.
SDK_BUCKET = 'chromiumos-sdk'
PREBUILTS_BUCKET = 'chromeos-prebuilt'


def RunSteps(
    api: recipe_api.RecipeApi,
    properties: build_sdk_pb2.BuildSDKProperties) -> result_pb2.RawResult:
  return BuildSDKRun(api, properties).run()


@dataclasses.dataclass
class GSURI:
  """Dataclass for a Google Storage URI.

  Attributes:
    bucket: The Google Storage bucket, such as "chromiumos-sdk".
    path: The path to the URI within the bucket, such as "foo/bar/baz.txt".
  """
  bucket: str
  path: str

  def __str__(self) -> str:
    """Format the URI as a full string."""
    return f'gs://{self.bucket}/{self.path}'


class BuildSDKRun:
  """Class to encapsulate a single run of the SDK builder."""

  def __init__(self, api: recipe_api.RecipeApi,
               properties: build_sdk_pb2.BuildSDKProperties):
    """Initialize the builder run."""
    self.m = api
    self.properties = properties

    # Paths of built files. These will be set after build API calls.
    self._host_prebuilts_dir: Optional[config_types.Path] = None
    self._target_prebuilts_dir: Optional[config_types.Path] = None
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

  def run(self) -> result_pb2.RawResult:
    """Run the main logic for this builder."""
    # Determine which commit
    with self._setup():
      self._build_sdk_packages()
      self._build_toolchain()
      self._create_sdk_tarball()
      self._create_sdk_manifest()
      self._upload_prebuilts()
      self._upload_sdk_tarball_and_manifest()
      self._update_gs_latest_file()
      self._report_uploads()
      if self.properties.launch_pupr:
        scheduled_pupr_build = self._schedule_uprev()
        return self._create_build_result(scheduled_pupr_build)
      return self._create_build_result(None)

  @contextlib.contextmanager
  def _setup(self) -> Generator:
    """Configure the builder and setup the workspace and chroot."""
    commit = None
    if self.properties.manifest_branch:
      commit = self.m.src_state.external_manifest.as_gitiles_commit_proto
      commit.ref = 'refs/heads/{}'.format(self.properties.manifest_branch)
    with self.m.build_menu.configure_builder(missing_ok=True, commit=commit), \
      self.m.build_menu.setup_workspace_and_chroot(
        bootstrap_chroot=True,
        replace=True):
      yield

  def _build_sdk_packages(self) -> None:
    """Build all packages for the SDK build target."""
    request = sdk_pb2.BuildPrebuiltsRequest(chroot=self.m.cros_sdk.chroot)
    response = self.m.cros_build_api.SdkService.BuildPrebuilts(request)
    self._host_prebuilts_dir = self.m.util.proto_path_to_recipes_path(
        response.host_prebuilts_path)
    self._target_prebuilts_dir = self.m.util.proto_path_to_recipes_path(
        response.target_prebuilts_path)
    self.m.path.mock_add_directory(self._host_prebuilts_dir)
    self.m.path.mock_add_directory(self._target_prebuilts_dir)

  def _build_toolchain(self) -> None:
    """Build cross-compiling toolchains for the SDK.

    This method sets the self._toolchain_tarball_paths attribute to a list
    of Paths of the generated toolchain tarballs.
    """
    request = sdk_pb2.BuildSdkToolchainRequest(
        chroot=self.m.cros_sdk.chroot,
        result_path=self.m.cros_build_api.new_result_path(),
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
    request = sdk_pb2.BuildSdkTarballRequest(
        chroot=self.m.cros_sdk.chroot,
        sdk_version=self.version,
    )
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

    Raises:
      AssertionError: If host prebuilts have not been built yet.
    """
    with self.m.step.nest('upload host prebuilts'):
      self._gsutil_upload(self._host_prebuilts_dir,
                          self._get_host_prebuilts_upload_uri())

  def _get_host_prebuilts_upload_uri(self) -> None:
    """Return the GS:// upload URI for the host binaries.

    The destination folder should be a URI like:
      gs://chromeos-prebuilt/host/amd64/amd64-host/chroot-${version}/packages/
    where ${version} is the SDK version.
    """
    dest_path = os.path.join('host', SDK_ARCH, SDK_BUILD_TARGET,
                             f'chroot-{self.version}', 'packages')
    return GSURI(self._pick_bucket(PREBUILTS_BUCKET), dest_path)

  def _upload_target_prebuilts(self) -> None:
    """Upload binaries for the amd64-host build target to GS://.

    Raises:
      AssertionError: If target prebuilts have not been built yet.
    """
    with self.m.step.nest('upload target prebuilts'):
      self._gsutil_upload(self._target_prebuilts_dir,
                          self._get_target_prebuilts_upload_uri())

  def _get_target_prebuilts_upload_uri(self) -> None:
    """Return the GS:// upload URI for the host binaries.

    The destination folder typically looks like:
      gs://chromeos-prebuilt/board/amd64-host/chroot-${version}/packages/
    where ${version} is the SDK version.
    """
    dest_path = os.path.join('board', SDK_BUILD_TARGET,
                             f'chroot-{self.version}', 'packages')
    return GSURI(self._pick_bucket(PREBUILTS_BUCKET), dest_path)

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
      ${TARGET} is the target architecture (ex. i686-cros-linux-gnu).
      ${VERSION} is the SDK version (ex. 2023.03.14.159265).
    For example:
      gs://chromiumos-sdk/2023/03/i686-cros-linux-gnu-2023.03.14.159265.tar.xz

    Args:
      source_path: The local path to the toolchain file.
    """
    basename = self.m.path.basename(source_path)
    with self.m.step.nest(f'upload {basename}'):
      upload_uri = self._get_toolchain_prebuilt_upload_uri(source_path)
      self._gsutil_upload(source_path, upload_uri)

  def _get_toolchain_prebuilt_upload_uri(
      self, source_path: config_types.Path) -> GSURI:
    """Return the GS:// upload URI for a toolchain prebuilt tarball.

    Args:
      source_path: The path to the toolchain tarball on the local filesystem.
    """
    basename = self.m.path.basename(source_path)
    target_architecture, ext = basename.split('.', 1)
    dest_basename = f'{target_architecture}-{self.version}.{ext}'
    return GSURI(
        self._pick_bucket(SDK_BUCKET),
        os.path.join(self._toolchain_tarball_dir, dest_basename))

  def _upload_sdk_tarball_and_manifest(self) -> None:
    """Upload the SDK tarball, and corresponding manifest, to GS://.

    Raises:
      AssertionError: If the SDK tarball or manifest has not been built yet.
    """
    with self.m.step.nest('upload sdk tarball and manifest'):
      self._upload_sdk_tarball()
      self._upload_sdk_manifest()

  def _upload_sdk_tarball(self) -> None:
    """Upload the SDK tarball to Google Storage.

    Raises:
      AssertionError: If the SDK tarball has not been built yet.
    """
    with self.m.step.nest('upload sdk tarball'):
      assert self._sdk_tarball_path is not None
      upload_uri = self._get_sdk_tarball_upload_uri()
      self._gsutil_upload(self._sdk_tarball_path, upload_uri)

  def _get_sdk_tarball_upload_uri(self) -> GSURI:
    """Return the GS:// upload URI for the SDK tarball.

    The SDK tarball should be uploaded to a URI like:
      gs://chromiumos-sdk/cros-sdk-${version}.tar.xz
    where ${version} is the SDK version.
    """
    return GSURI(
        self._pick_bucket(SDK_BUCKET), f'cros-sdk-{self.version}.tar.xz')

  def _upload_sdk_manifest(self) -> None:
    """Upload the SDK tarball to Google Storage.

    Raises:
      AssertionError: If the SDK manifest has not been built yet.
    """
    with self.m.step.nest('upload sdk manifest'):
      assert self._sdk_manifest_path is not None
      upload_uri = self._get_sdk_manifest_upload_uri()
      self._gsutil_upload(self._sdk_manifest_path, upload_uri)

  def _get_sdk_manifest_upload_uri(self) -> GSURI:
    """Return the GS:// upload URI for the SDK manifest file.

    The SDK manifest should be uploaded to a URI like:
      gs://chromiumos-sdk/cros-sdk-${version}.tar.xz.Manifest
    where ${version} is the SDK version.
    """
    sdk_tarball_uri = self._get_sdk_tarball_upload_uri()
    return GSURI(sdk_tarball_uri.bucket, f'{sdk_tarball_uri.path}.Manifest')

  def _update_gs_latest_file(self) -> None:
    """Update the GS:// latest SDK file to point to the newly built SDK."""
    with self.m.step.nest('update gs:// latest file') as presentation:
      old_contents = self._read_existing_gs_latest_file()
      new_contents = self.m.key_value_store.update_one_value(
          old_contents, 'LATEST_SDK_UPREV_TARGET', self.version, True)
      tempfile = self.m.path.mkstemp()
      self.m.file.write_text('write local file to upload', tempfile,
                             new_contents)
      dest_uri = GSURI(self._pick_bucket(SDK_BUCKET), 'cros-sdk-latest.conf')
      self._gsutil_upload(tempfile, dest_uri)
      presentation.properties['new_LATEST_SDK_UPREV_TARGET'] = self.version

  def _report_uploads(self) -> None:
    """Report what files were uploaded to Google Storage."""
    with self.m.step.nest('report uploads') as presentation:
      names_to_uris: Dict[str, str] = {
          'sdk_tarball': str(self._get_sdk_tarball_upload_uri()),
          'sdk_manifest': str(self._get_sdk_manifest_upload_uri()),
          'host_prebuilts': str(self._get_host_prebuilts_upload_uri()),
          'target_prebuilts': str(self._get_target_prebuilts_upload_uri()),
      }
      for local_tc_path in self._toolchain_tarball_paths:
        target_arch = self.m.path.basename(local_tc_path).split('.', 1)[0]
        tc_uri = str(self._get_toolchain_prebuilt_upload_uri(local_tc_path))
        names_to_uris[f'toolchain_prebuilts_{target_arch}'] = tc_uri
      for name, uri in names_to_uris.items():
        presentation.links[name] = uri
      self.m.easy.set_properties_step(uploaded_files=names_to_uris)

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
          'LATEST_SDK', 'None')
      presentation.properties[
          'old_LATEST_SDK_UPREV_TARGET'] = contents_dict.get(
              'LATEST_SDK_UPREV_TARGET', 'None')
    return contents

  def _pick_bucket(self, prod_bucket: str) -> str:
    """Return a bucket for uploading based on whether this is a staging builder.

    The staging builder deliberately doesn't have write access to most buckets.
    Thus, the staging builder should upload to staging buckets instead.

    Args:
      prod_bucket: The bucket to return if this is a prod builder.

    Returns:
      A bucket name (without the gs:// prefix).
    """
    if self.m.build_menu.is_staging:
      return f'staging-{prod_bucket}'
    return prod_bucket

  def _gsutil_upload(self, source_path: config_types.Path,
                     dest_uri: GSURI) -> None:
    """Wrapper around self.m.gsutil.upload() with some common functionality.

    Fails if the source path is not present on the filesystem.

    Always uploads directories with -r for recursive mode, and multithreaded.

    Always uploads with the `public-read` canned ACL, since SDK artifacts can
    be used by anybody.

    Args:
      source_path: Local filepath to upload.
      dest_uri: The Google Storage location to upload to.

    Raises:
      InfraFailure: If the local filepath is not present on the filesystem.
    """
    # It's easiest to mock the paths into existence as soon as the BAPI returns
    # them. So currently I don't have a great way to test the case where we want
    # to upload a path that doesn't exist.
    if not self.m.path.exists(source_path):  # pragma: nocover
      raise recipe_api.InfraFailure(
          f'Upload source "{source_path}" not found locally.')
    args = []
    # gs://staging-chromiumos-sdk has uniform bucket-level access = public-read.
    # Trying to set ACLs via `gustil -a` gets an HTTP error.
    if dest_uri.bucket != 'staging-chromiumos-sdk':
      args.extend(['-a', 'public-read'])
    if self.m.path.isdir(source_path):
      args.append('-r')
      multithreaded = True
    else:
      multithreaded = False
    self.m.gsutil.upload(
        str(source_path), dest_uri.bucket, dest_uri.path, args=args,
        multithreaded=multithreaded)

  def _schedule_uprev(self) -> build_pb2.Build:
    """Trigger a PUpr build to uprev to the newly-built SDK.

    The PUpr build should be staging if this build is staging, and prod if this
    build is prod.

    PUpr uses GitilesTriggers to pick a branch policy, because originally all
    uprevs were triggered by gitiles changes. Luckily, it provides a property
    for spoofing GitilesTriggers.

    Returns:
      A Build proto message for the scheduled build.
    """
    if self.m.build_menu.is_staging:
      bucket, builder = 'staging', 'staging-chromiumos-sdk-pupr-generator'
    else:
      bucket, builder = 'pupr', 'chromiumos-sdk-pupr-generator'

    # PUpr uses its GitilesTriggers to pick a branch policy, because originally
    # PUpr was always triggered by gitiles changes. Today, it allows spoofing
    # GitilesTriggers via input properties. The embedded ref is useful because
    # it tells PUpr which branch to upload to.
    # The repo and revision should be unnecessary.
    if self.properties.manifest_branch:
      upload_ref = f'refs/heads/{self.properties.manifest_branch}'
    else:
      upload_ref = 'refs/heads/main'
    pupr_trigger = triggers_pb2.Trigger(
        gitiles=triggers_pb2.GitilesTrigger(ref=upload_ref))

    pupr_properties = {
        '$chromeos/pupr_local_uprev':
            json_format.MessageToDict(
                pupr_local_uprev_pb2.PuprLocalUprevProperties(
                    sdk_uprev_spec=pupr_local_uprev_pb2.SdkUprevSpec(
                        sdk_version=self.version,
                        toolchain_template=self._toolchain_tarball_template,
                    ))),
        'triggers': [json_format.MessageToDict(pupr_trigger)],
    }
    if self.properties.pupr_branch_policy != generator_pb2.BranchPolicy():
      pupr_properties['branch_policies'] = [
          json_format.MessageToDict(self.properties.pupr_branch_policy)
      ]

    request = self.m.buildbucket.schedule_request(
        builder=builder,
        bucket=bucket,
        properties=pupr_properties,
        can_outlive_parent=True,
    )
    builds = self.m.buildbucket.schedule([request], step_name='schedule uprev')
    assert len(builds) == 1
    return builds[0]

  def _create_build_result(
      self,
      scheduled_pupr_build: Optional[build_pb2.Build]) -> result_pb2.RawResult:
    """Return a RawResult summarizing this build_sdk build.

    Args:
      scheduled_pupr_build: If given, a proto message of the PUpr build that
        this build launched.
    """
    summary_lines = []
    sdk_gs_link = self._get_gs_link_to_sdk()
    summary_lines.append(f'Built SDK version [{self.version}]({sdk_gs_link}).')
    if scheduled_pupr_build is None:
      summary_lines.append('SDK uprev builder not launched.')
    else:
      pupr_link = self.m.buildbucket.build_url(build_id=scheduled_pupr_build.id)
      summary_lines.append(f'Launched SDK uprev build: {pupr_link}')
    return result_pb2.RawResult(status=bb_common_pb2.SUCCESS,
                                summary_markdown='\n'.join(summary_lines))

  def _get_gs_link_to_sdk(self) -> str:
    """Return a gs:// link to the built SDK tarball."""
    bucket = self._pick_bucket(SDK_BUCKET)
    return f'gs://{bucket}/cros-sdk-{self.version}.tar.xz'


def GenTests(api: recipe_test_api.RecipeTestApi):
  # RE_GSUTIL is a regex that looks for a path ending in 'gsutil.py'.
  # This is useful for post_process.StepCommandContains, since we don't really
  # care about the full path to gsutil.py.
  RE_GSUTIL = re.compile(r'gsutil\.py$')

  # DEFAULT_VERSION is a parsing of the buildbucket API's default start_time.
  DEFAULT_VERSION = '1970.01.01.000000'

  yield api.test(
      'basic',
      api.properties(launch_pupr=True),
      api.post_check(post_process.PropertyEquals, 'version', DEFAULT_VERSION),
      # Make sure we're not updating the chroot, since we need to ensure that
      # all host packages can be built using the bootstrap SDK version.
      # TODO(b/311189070): Re-enable this check.
      # api.post_check(post_process.DoesNotRun, 'update sdk'),
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
          'old_LATEST_SDK',
          '2023.03.13.222421',
      ),
      api.post_check(
          post_process.PropertyEquals,
          'old_LATEST_SDK_UPREV_TARGET',
          '2023.03.14.159265',
      ),
      api.post_check(
          post_process.PropertyEquals,
          'new_LATEST_SDK_UPREV_TARGET',
          DEFAULT_VERSION,
      ),
      # Prod builder should run prod PUpr.
      api.post_check(post_process.MustRun, 'schedule uprev'),
      api.post_check(post_process.LogContains, 'schedule uprev', 'request', [
          '"bucket": "pupr"', '"builder": "chromiumos-sdk-pupr-generator"',
          '"sdkVersion": "1970.01.01.000000"',
          '"toolchainTemplate": "1970/01/%(target)s-1970.01.01.000000.tar.xz"',
          '"ref": "refs/heads/main'
      ]),
      api.post_check(post_process.LogDoesNotContain, 'schedule uprev',
                     'request', ['"branch_policies":']),
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
      # These steps should all upload to staging buckets.
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload host prebuilts.gsutil upload', [
              'gs://staging-chromeos-prebuilt/host/amd64/amd64-host/chroot-1970.01.01.000000/packages'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload target prebuilts.gsutil upload', [
              'gs://staging-chromeos-prebuilt/board/amd64-host/chroot-1970.01.01.000000/packages'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload sdk toolchain tarballs.upload foo.tar.xz.gsutil upload',
          ['gs://staging-chromiumos-sdk/1970/01/foo-1970.01.01.000000.tar.xz']),
      api.post_check(
          post_process.StepCommandContains,
          'upload prebuilts.upload sdk toolchain tarballs.upload bar.tar.xz.gsutil upload',
          ['gs://staging-chromiumos-sdk/1970/01/bar-1970.01.01.000000.tar.xz']),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk tarball.gsutil upload',
          ['gs://staging-chromiumos-sdk/cros-sdk-1970.01.01.000000.tar.xz']),
      api.post_check(
          post_process.StepCommandContains,
          'upload sdk tarball and manifest.upload sdk manifest.gsutil upload', [
              'gs://staging-chromiumos-sdk/cros-sdk-1970.01.01.000000.tar.xz.Manifest'
          ]),
      api.post_check(
          post_process.StepCommandDoesNotContain,
          'upload prebuilts.upload sdk toolchain tarballs.upload foo.tar.xz.gsutil upload',
          ['-a']),
      # Staging builder should launch the staging PUpr.
      api.post_check(post_process.MustRun, 'schedule uprev'),
      api.post_check(post_process.LogContains, 'schedule uprev', 'request',
                     (r'"bucket": "staging"',
                      r'"builder": "staging-chromiumos-sdk-pupr-generator"')),
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

  yield api.build_menu.test(
      'build-on-branch',
      api.properties(launch_pupr=True, manifest_branch='stabilize-1337.B'),
      api.post_check(post_process.LogContains, 'schedule uprev', 'request',
                     ['"ref": "refs/heads/stabilize-1337.B']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.build_menu.test(
      'override-pupr-branch-policy',
      api.properties(
          launch_pupr=True, pupr_branch_policy=generator_pb2.BranchPolicy(
              reviewers=[generator_pb2.Reviewer(email='sundar@google.com')])),
      api.post_check(post_process.LogContains, 'schedule uprev', 'request',
                     ['"branch_policies":', '"email": "sundar@google.com"']),
      api.post_process(post_process.DropExpectation),
  )
