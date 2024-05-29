# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating Parallels uprev CLs.

This recipe generates CLs to uprev Parallels binaries. As part of these
CLs, a new Parallels VM image is produced for testing.

This recipe involves booting up Windows in a virtual machine. The
caller is responsible for ensuring this is only invoked in contexts
where the necessary license(s) have been obtained.
"""
import datetime
import json
import re
from collections import namedtuple
from typing import Dict, Optional

from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry
from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipes.chromeos.build_parallels_image import BuildParallelsImageProperties
from PB.recipes.chromeos.uprev_parallels_pin import UprevParallelsPinProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi


DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'recipe_engine/time',
    'build_menu',
    'cros_artifacts',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'repo',
    'naming',
]

PROPERTIES = UprevParallelsPinProperties

_PANTHEON_PREFIX = 'https://pantheon.corp.google.com/storage/browser'
_BUILD_STEP_NAME = 'build chromiumos with upreved Parallels'
_IMAGE_STEP_NAME = 'build VM image'
_SNAPSHOT_STEP_NAME = 'find latest green snapshot'

BuildPath = namedtuple('BuildPath', ['bucket', 'path'])
VersionPin = namedtuple('VersionPin', ['version', 'test_image'])


def RunSteps(api: RecipeApi, properties: UprevParallelsPinProperties):
  with api.step.nest('validate properties') as presentation:
    if not properties.HasField('package_info'):
      raise StepFailure('must set package_info')
    if not properties.upstream_gs_bucket:
      raise StepFailure('must set upstream_gs_bucket')
    if not properties.upstream_gs_path:
      raise StepFailure('must set upstream_gs_path')
    if not properties.test_image_gs_bucket:
      raise StepFailure('must set test_image_gs_bucket')
    if not properties.test_image_gs_path:
      raise StepFailure('must set test_image_gs_path')
    if not properties.version_file:
      raise StepFailure('must set version_file')

    presentation.step_text = 'all properties good'

  package = properties.package_info

  upstream_version = get_upstream_version(api, properties)

  # Build a version of CrOS with the new Parallels version. If build is not
  # required (because upstream_version is the current version), returns None.
  build_path = build_os_with_uprev(api, properties, package, upstream_version)
  if build_path:
    # Build a new VM image.
    test_image = build_vm_image(api, properties, build_path, upstream_version)
    # Update VERSION-PIN
    new_pin = VersionPin(upstream_version, test_image)
    commit_pin_uprev(api, properties, package, new_pin)


def build_os_with_uprev(api: RecipeApi, properties: UprevParallelsPinProperties,
                        package: PackageInfo,
                        upstream_version: str) -> Optional[BuildPath]:
  """Builds a version of CrOS with given version of the Parallels package.

  The build will still contain an old VM image for testing.

  Args:
    package: the identify of the Parallels package.
    upstream_version: the version of Parallels to include in the build.

  Returns:
    Where the build artifacts were uploaded.
  """
  with api.step.nest(_BUILD_STEP_NAME) as presentation:
    commit = get_latest_green_snapshot_commit(api,
                                              api.build_menu.build_target.name)
    with api.build_menu.configure_builder(commit=commit) as config, \
        api.build_menu.setup_workspace_and_chroot():

      version_pin = get_version_pin(api, properties)
      if not is_version_after(upstream_version, version_pin.version):
        if api.build_menu.is_staging:
          presentation.step_text = 'build not required, but forcing anyway to'\
            ' test recipe in staging'
        else:
          presentation.step_text = 'build not required, Parallels already up'\
            ' to date.'
          return None

      uprev_package(api, properties, package, upstream_version)

      env_info = api.build_menu.setup_sysroot_and_determine_relevance()
      packages = env_info.packages

      failing_build_exception = None
      try:
        api.build_menu.bootstrap_sysroot(config)
        api.build_menu.install_packages(config, packages)
        api.build_menu.build_and_test_images(config)
      except StepFailure as sf:
        # If we catch an exception, swallow it and store it so the next steps can
        # still occur; there is value in uploading the artifact even
        # in cases of build failure for debug purposes.
        failing_build_exception = sf

      try:
        api.build_menu.upload_artifacts(
            config,
            ignore_breakpad_symbol_generation_errors=failing_build_exception
            is not None)
      except StepFailure as sf:
        # If upload_artifacts threw an exception, surface that exception unless
        # build_and_test_images above threw an exception, in which case we want to
        # surface *that* exception for accuracy in reporting the build (and it's
        # likely that upload artifacts failed as a result of those previous issues).
        raise failing_build_exception or sf

      # Now that upload_artifacts is done, surface any exceptions from earlier.
      if failing_build_exception:
        raise failing_build_exception  # pylint: disable=raising-bad-type

      with api.step.nest('get artifacts path'):
        gs_path = api.cros_artifacts.artifacts_gs_path(
            config.id.name, api.build_menu.build_target, config.id.type)
        presentation.links['build artifacts'] = '{}/{}/{}'.format(
            _PANTHEON_PREFIX, config.artifacts.artifacts_gs_bucket, gs_path)
        return BuildPath(config.artifacts.artifacts_gs_bucket, gs_path)


def uprev_package(api: RecipeApi, properties: UprevParallelsPinProperties,
                  package: PackageInfo, to_version: str):
  """Uprevs the Parallels package to the given version.

  The Parallels package will be upreved on the local checkout to the given
  version.

  Args:
    package: the package to uprev.
    to_version: the version to uprev to.
  """
  package_title = api.naming.get_package_title(package)
  with api.step.nest('try uprev {}'.format(package_title)) as presentation:
    # Update pinned version to to_version, but don't change the test_image.
    version_pin = get_version_pin(api, properties)
    version_pin = VersionPin(to_version, version_pin.test_image)
    set_version_pin(api, properties, version_pin)

    request = UprevVersionedPackageRequest(
        chroot=api.cros_sdk.chroot,
        package_info=package,
        versions=[
            # Pass a dummy GitRef, as one is required by the
            # UprevVersionedPackage endpoint.
            UprevVersionedPackageRequest.GitRef(
                repository=properties.upstream_gs_bucket, ref=to_version,
                revision='')
        ],
        build_targets=[])
    response = api.cros_build_api.PackageService.UprevVersionedPackage(
        request, name='uprev versioned package')

    presentation.logs['uprev versions'] = [
        response.version for response in response.responses
    ]


@exponential_retry(retries=1, delay=datetime.timedelta(seconds=1))
def build_vm_image(api: RecipeApi, properties: UprevParallelsPinProperties,
                   artifacts_path: BuildPath,
                   parallels_version: str) -> Dict[str, str]:
  """Builds a new VM image for testing.

  Args:
    artifacts_path: The location of build output artifacts.
    parallels_version: The Parallels version included in the given build.

  Returns:
    The details of the new test image.
  """
  with api.step.nest(_IMAGE_STEP_NAME) as presentation:
    presentation.links['destination directory'] = '{}/{}/{}'.format(
        _PANTHEON_PREFIX, properties.test_image_gs_bucket,
        properties.test_image_gs_path)

    bucket = 'infra'
    builder = 'build-parallels-image'
    if api.build_menu.is_staging:
      bucket = 'staging'
      builder = 'staging-build-parallels-image'

    request = api.buildbucket.schedule_request(
        bucket=bucket, builder=builder, properties=json_format.MessageToDict(
            BuildParallelsImageProperties(
                build_gs_bucket=artifacts_path.bucket,
                build_gs_path=artifacts_path.path,
                test_image_gs_bucket=properties.test_image_gs_bucket,
                test_image_gs_path=properties.test_image_gs_path,
                parallels_version=parallels_version,
                user_acls=properties.user_acls,
                group_acls=properties.group_acls,
            )), swarming_parent_run_id=api.swarming.task_id)

    # Invoke the build-parallels-image builder to build the VM image
    # on real hardware and wait for it to compelte.
    build = api.buildbucket.run([request], timeout=4 * 3600,
                                step_name='run ' + builder)[0]
    if build.status != common_pb2.SUCCESS:
      raise StepFailure('Triggered VM image build did not succeed')

    # The build output contains other fields, which are not in
    # BuildParallelsImageProperties. These can be safely ignored.
    output = json_format.ParseDict(js_dict=build.output.properties,
                                   message=BuildParallelsImageProperties(),
                                   ignore_unknown_fields=True)

    presentation.links['uploaded image'] = '{}/{}/{}/{}'.format(
        _PANTHEON_PREFIX, properties.test_image_gs_bucket,
        properties.test_image_gs_path, output.image_name)

    # This blob is defined by tast. See go/tast-writing#external-data-files.
    image_details = {
        'url':
            'gs://{}/{}/{}'.format(properties.test_image_gs_bucket,
                                   properties.test_image_gs_path,
                                   output.image_name),
        'size':
            output.image_size,
        'sha256sum':
            output.image_sha256,
    }
    presentation.logs['image metadata'] = json.dumps(image_details,
                                                     separators=(',', ':'),
                                                     sort_keys=True, indent=2)
    return image_details


def commit_pin_uprev(api: RecipeApi, properties: UprevParallelsPinProperties,
                     package: PackageInfo, new_version_pin: VersionPin):
  """Commits and uploads the uprev of the version-pin file.

  Args:
    package: the package to include in the commit message.
    new_version_pin: the new version pin data.
  """
  with api.step.nest('update VERSION-PIN') as presentation:
    with api.cros_source.checkout_overlays_context():
      api.cros_source.ensure_synced_cache()
      set_version_pin(api, properties, new_version_pin)

      message = '{}: updating version pin to latest - {}'.format(
          package.package_name, new_version_pin.version)

      version_path = get_version_path(api, properties)
      package_path = api.path.dirname(version_path)

      with api.step.nest('commit uprev'), \
            api.context(cwd=api.path.abs_to_path(package_path)):
        project = api.repo.project_info(project=api.git.repository_root())
        api.repo.start('uprev-parallels-pin', projects=[project.name])

        api.git.add([version_path])
        api.git.commit(message)

      # In staging, do not upload the CL to gerrit.
      if not api.build_menu.is_staging:
        with api.step.nest('upload CL to gerrit'):
          change = api.gerrit.create_change(project=project.name,
                                            topic=properties.topic)
          labels = {
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          }
          api.gerrit.set_change_labels(change, labels)

          presentation.links[
              'uploaded CL'] = api.gerrit.parse_gerrit_change_url(change)


def get_upstream_version(api: RecipeApi,
                         properties: UprevParallelsPinProperties) -> str:
  """Gets the latest version of Parallels from the upstream bucket.

  Returns:
    The latest upstream version of Parallels.
  """
  with api.step.nest('find latest upstream version') as presentation:
    presentation.links['upstream directory'] = '{}/{}/{}'.format(
        _PANTHEON_PREFIX, properties.upstream_gs_bucket,
        properties.upstream_gs_path)

    gs_path = 'gs://{}/{}'.format(properties.upstream_gs_bucket,
                                  properties.upstream_gs_path)
    files = api.gsutil.list(
        gs_path, stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(
            'gs://chromeos-binaries/path/parallels-desktop-1.0.0.9000.tbz2\n'
            'gs://chromeos-binaries/path/random-file.txt\n'
            'gs://chromeos-binaries/path/parallels-desktop-1.0.1.812.tbz2\n'
            'gs://chromeos-binaries/path/parallels-desktop-1.0.1.1098.tbz2\n'
            'gs://chromeos-binaries/path/parallels-desktop-1.0.1.100.tbz2\n'))
    versions = []
    for filepath in files.stdout.decode('utf-8').splitlines():
      match = re.match(r'.*-([0-9]+(\.[0-9]+)+)\.tbz2', filepath)
      if match is None:
        continue
      # parse version into list[int]
      version_parts = list(map(int, match.group(1).split('.')))
      versions.append(version_parts)

    if not versions:
      raise StepFailure('Upstream repository has no files matching pattern.')

    # Sort lexicographically, in descending order.
    versions.sort(reverse=True)
    result = '.'.join(map(str, versions[0]))
    presentation.step_text = 'found version: {}'.format(result)
    return result


def get_version_pin(api: RecipeApi,
                    properties: UprevParallelsPinProperties) -> VersionPin:
  """Reads and returns the content of the VERSION-PIN file.

  Before calling this function, ensure a synced version of the source must
  have been checked out.

  Returns:
    The pinned version data.
  """
  with api.step.nest('read pinned version file') as presentation:
    version_path = get_version_path(api, properties)
    version_json = api.file.read_json(
        name='VERSION-PIN', source=version_path, test_data={
            'version': '1.0.1.1000',
            'test_image': {
                'opaque': 'data'
            }
        })
    result = VersionPin(version_json['version'], version_json['test_image'])
    presentation.step_text = 'pinned version: {}'.format(result.version)
    return result


def set_version_pin(api: RecipeApi, properties: UprevParallelsPinProperties,
                    new_version: VersionPin):
  """Sets the content of the VERSION-PIN file.

  Before calling this function, ensure a synced version of the source must
  have been checked out.

  Args:
    new_version: the new version pin data.
  """
  with api.step.nest('write pinned version file'):
    version_path = get_version_path(api, properties)
    api.file.write_json(
        name='VERSION-PIN', dest=version_path, data={
            'version': new_version.version,
            'test_image': new_version.test_image
        }, indent=2)


def get_version_path(api: RecipeApi, properties: UprevParallelsPinProperties):
  """Gets the path of the VERSION-PIN file."""
  return api.cros_source.workspace_path / properties.version_file


def is_version_after(version: str, previous_version: str) -> bool:
  """Returns if version occurs logically after pervious_version.

  For example, is_version_after('1.0.3.1', '1.0.2.2') returns true.

  Args:
    version: The version to compare.
    previous_version: The previous version to compare with.
  """
  parts = list(map(int, version.split('.')))
  previous_parts = list(map(int, previous_version.split('.')))
  # list comparison performs lexicographic comparison.
  return parts > previous_parts


def get_latest_green_snapshot_commit(api: RecipeApi,
                                     build_target: str) -> GitilesCommit:
  """Finds the latest green snapshot build for the given build target
  and returns the corresponding manifest gitiles (input) commit.

  Args:
    build_target: The name of the build target."""
  with api.step.nest(_SNAPSHOT_STEP_NAME) as presentation:
    fields = frozenset({'id', 'builder', 'status', 'input'})
    # Returns the latest green snapshot build (limited to
    # the last two weeks). Search always returns the newest build
    # first.
    builds = api.buildbucket.search(
        predicate=builds_service_pb2.BuildPredicate(
            builder=builder_common_pb2.BuilderID(
                project=api.buildbucket.build.builder.project,
                bucket='postsubmit',
                builder='{}-snapshot'.format(build_target),
            ), create_time=common_pb2.TimeRange(
                start_time=timestamp_pb2.Timestamp(
                    seconds=api.buildbucket.build.create_time.ToSeconds() -
                    14 * 24 * 60 * 60)), status=common_pb2.SUCCESS),
        fields=fields, limit=1)

    if not builds:
      raise StepFailure(
          'unable to find builds for {}-snapshot'.format(build_target))

    presentation.links['latest green snapshot'] = api.buildbucket.build_url(
        build_id=builds[0].id)
    return builds[0].input.gitiles_commit


def GenTests(api: RecipeTestApi):
  good_props = {
      '$chromeos/cros_relevance': {
        'force_postsubmit_relevance': True
      },
      '$chromeos/overlayfs': {
          'random_work_path': True
      },
      '$chromeos/tast_results': {
          'archive_gs_bucket': 'chromeos-parallels-uprev-archive',
      },
      'package_info': {
          'category': 'app-emulation',
          'package_name': 'parallels-desktop'
      },
      'upstream_gs_bucket':
          'chromeos-binaries',
      'upstream_gs_path':
          'HOME/bcs-pita-private/project-pita-private/app-emulation/'\
            'parallels-desktop/',
      'test_image_gs_bucket':
          'chromeos-test-assets-private',
      'test_image_gs_path':
          'tast/pita/pita',
      'version_file':
          'src/private-overlays/chromeos-partner-overlay/app-emulation/'\
            'parallels-desktop/VERSION-PIN',
      'user_acls': ['owner@google.com:OWNER', 'reader@google.com:READ'],
      'group_acls': ['aclgroup@google.com:READ']
  }

  snapshot_builds = []
  snapshot_builds.append(
      build_pb2.Build(
          id=18101, status=common_pb2.SUCCESS, input=build_pb2.Build.Input(
              gitiles_commit={
                  'host': 'chrome-internal.googlesource.com',
                  'ref': 'refs/heads/snapshot',
                  'project': 'chromeos/manifest-internal',
                  'id': 'latest-green-snapshot-SHA'
              })))

  good_snapshot_search = api.buildbucket.simulated_search_results(
      snapshot_builds,
      step_name='{}.{}.buildbucket.search'.format(_BUILD_STEP_NAME,
                                                  _SNAPSHOT_STEP_NAME))
  bad_snapshot_search = api.buildbucket.simulated_search_results(
      [], step_name='{}.{}.buildbucket.search'.format(_BUILD_STEP_NAME,
                                                      _SNAPSHOT_STEP_NAME))

  props = good_props.copy()
  del props['package_info']
  # Test missing recipe parameters.
  yield api.build_menu.test(
      'no-package', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  props = good_props.copy()
  del props['upstream_gs_bucket']
  yield api.build_menu.test(
      'no-upstream-bucket', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  props = good_props.copy()
  del props['upstream_gs_path']
  yield api.build_menu.test(
      'no-upstream-path', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  props = good_props.copy()
  del props['version_file']
  yield api.build_menu.test(
      'no-version-file', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  props = good_props.copy()
  del props['test_image_gs_bucket']
  yield api.build_menu.test(
      'no-test-image-bucket', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  props = good_props.copy()
  del props['test_image_gs_path']
  yield api.build_menu.test(
      'no-test-image-path', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  # Upstream version cannot be found.
  yield api.build_menu.test(
      'no-upstream-version', api.properties(**good_props),
      api.step_data('find latest upstream version.gsutil list',
                    stdout=api.raw_io.output('')),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  yield api.build_menu.test(
      'snapshot-not-found', api.properties(**good_props), bad_snapshot_search,
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE')

  # Upstream version is the same as in CrOS (nothing to do).
  yield api.build_menu.test(
      'uprev-not-required', api.properties(**good_props), good_snapshot_search,
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.step_data(
          _BUILD_STEP_NAME + '.read pinned version file.VERSION-PIN',
          api.file.read_json({
              'version': '1.0.1.1098',
              'test_image': {
                  'opaque': 'data'
              }
          })))

  # Various build errors
  yield api.build_menu.test(
      'install-packages-fail', api.properties(**good_props),
      good_snapshot_search, api.git.diff_check(True),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.upload artifacts.publish artifacts'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.install packages',
          'SysrootService/InstallPackages', retcode=1), status='FAILURE')

  yield api.build_menu.test(
      'bundle-fail', api.properties(**good_props), api.git.diff_check(True),
      good_snapshot_search,
      api.post_check(post_process.MustRun, _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.upload artifacts.call artifacts service',
          'ArtifactsService/Get', retcode=1), status='INFRA_FAILURE')

  yield api.build_menu.test(
      'install-packages-and-bundle-fail', api.properties(**good_props),
      good_snapshot_search, api.git.diff_check(True),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.install packages',
          'SysrootService/InstallPackages', retcode=1),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.upload artifacts.call artifacts service',
          'ArtifactsService/Get', retcode=1), status='FAILURE')

  # Build image fails to schedule (infra failure)
  yield api.build_menu.test(
      'build-image-schedule-failure',
      api.properties(**good_props),
      good_snapshot_search,
      api.git.diff_check(True),
      api.override_step_data(
          '{}.run build-parallels-image.schedule'.format(_IMAGE_STEP_NAME),
          api.json.invalid(None), retcode=1),
      # Failure is permanant, so persists after retry.
      api.override_step_data(
          '{} (2).run build-parallels-image.schedule'.format(_IMAGE_STEP_NAME),
          api.json.invalid(None), retcode=1),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='INFRA_FAILURE',
  )

  # Build image fails
  yield api.build_menu.test(
      'build-image-collect-failure',
      api.properties(**good_props),
      good_snapshot_search,
      api.git.diff_check(True),
      api.buildbucket.simulated_collect_output([
          api.buildbucket.try_build_message(build_id=8922054662172514000,
                                            status='FAILURE'),
      ], step_name='{}.run build-parallels-image.collect'.format(
          _IMAGE_STEP_NAME)),
      # Failure is permanant, so persists after retry.
      api.buildbucket.simulated_collect_output([
          api.buildbucket.try_build_message(build_id=8922054662172514001,
                                            status='FAILURE'),
      ], step_name='{} (2).run build-parallels-image.collect'.format(
          _IMAGE_STEP_NAME)),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      status='FAILURE',
  )

  # Success
  build_success = build_pb2.Build(
      id=8922054662172514000, number=1234, builder=builder_common_pb2.BuilderID(
          project='chromeos',
          bucket='infra',
          builder='build-parallels-image',
      ), created_by='user:luci-scheduler@appspot.gserviceaccount.com',
      create_time=timestamp_pb2.Timestamp(seconds=1527292217),
      status=common_pb2.SUCCESS, output=build_pb2.Build.Output())
  build_success.output.properties.update({
      '$recipe_engine/path': {
          'other': 'properties'
      },
      'image_name': 'pre_pluginvm_image_1.2.3.4_20201127.zip',
      'image_size': 9876543210,
      'image_sha256': 'aabbccddeeff0011223344556677889900',
  })
  yield api.build_menu.test(
      'uprev-success',
      api.properties(**good_props),
      api.git.diff_check(True),
      good_snapshot_search,
      api.buildbucket.simulated_collect_output(
          [build_success],
          step_name=_IMAGE_STEP_NAME + '.run build-parallels-image.collect'),
      api.post_check(post_process.MustRun, _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.MustRun, _IMAGE_STEP_NAME),
      api.post_check(post_process.MustRun, 'update VERSION-PIN'),
  )

  # Staging success
  staging_build_success = build_pb2.Build(
      id=8922054662172514000, number=1234, builder=builder_common_pb2.BuilderID(
          project='chromeos',
          bucket='staging',
          builder='staging-build-parallels-image',
      ), created_by='user:luci-scheduler@appspot.gserviceaccount.com',
      create_time=timestamp_pb2.Timestamp(seconds=1527292217),
      status=common_pb2.SUCCESS, output=build_pb2.Build.Output())
  staging_build_success.output.properties.update({
      '$recipe_engine/path': {
          'other': 'properties'
      },
      'image_name': 'pre_pluginvm_image_1.2.3.4_20201127.zip',
      'image_size': 9876543210,
      'image_sha256': 'aabbccddeeff0011223344556677889900',
  })
  yield api.build_menu.test(
      'uprev-success-staging', api.properties(**good_props),
      good_snapshot_search,
      # Simulate no uprev required. Staging builder should still run.
      api.step_data(
          _BUILD_STEP_NAME + '.read pinned version file.VERSION-PIN',
          api.file.read_json({
              'version': '1.0.1.1098',
              'test_image': {
                  'opaque': 'data'
              }
          })),
      api.git.diff_check(True),
      api.buildbucket.simulated_collect_output(
          [staging_build_success],
          step_name=_IMAGE_STEP_NAME\
              + '.run staging-build-parallels-image.collect'),
      api.post_check(post_process.MustRun, _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.MustRun, _IMAGE_STEP_NAME),
      api.post_check(post_process.MustRun, 'update VERSION-PIN'),
      # Leverage test data for existing snapshot builder.
      builder='amd64-generic-snapshot', bucket='staging')
