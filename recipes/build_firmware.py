# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds and tests firmware.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
This recipe should only be used for ToT firmware builds and build_legacy_fw
(which is not deprecated) should be used for branch firmware builds. It is
also acceptable to use for short-lived EC branches. There is DANGER that
there could be unexpected interactions between unbranched recipes and branched
cros_build_api calls. You are on your own if you attempt to use this recipe on
a branch, and that branch should be as short-lived as possible.
"""

import collections
import os
from pathlib import Path

from google.protobuf import json_format
from google.protobuf.json_format import MessageToDict
from google.protobuf import struct_pb2

import PB.chromiumos.common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_engine import result as result_pb2
from PB.chromite.api.firmware import BuildAllFirmwareRequest, FirmwareTarget
from PB.chromite.api.firmware import FirmwareArtifactInfo
from PB.chromite.api.firmware import TestAllFirmwareRequest
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.build_report import BuildReport
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/bcid_reporter',
    'recipe_engine/context',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'build_reporting',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_release',
    'cros_sdk',
    'cros_source',
    'cros_version',
    'deferrals',
    'easy',
    'failures',
    'mutable_output',
    'signing',
    'signing_utils',
    'src_state',
    'test_util',
]


PROPERTIES = BuildFirmwareProperties

def UploadTestResults(api, location, builder_name):
  if location == common_pb2.PLATFORM_ZEPHYR:
    cros_src_path = api.cros_source.workspace_path
    with api.step.nest('Upload EC Firmware test results') as pres:
      for test_results in api.file.glob_paths(
          'twister dirs', cros_src_path,
          'src/platform/ec/twister-out*/twister.json', test_data=[
              'src/platform/ec/twister-out-host/twister.json',
              'src/platform/ec/twister-out-llvm/twister.json'
          ]):
        try:
          rdb_cmd = [
              'vpython3',
              cros_src_path / 'src/platform/ec/util/zephyr_to_resultdb.py',
              '--result=' + str(test_results), '--upload=True'
          ]
          base_variant = {'builder_name': builder_name}
          api.step('run', api.resultdb.wrap(rdb_cmd, base_variant=base_variant))

        except StepFailure:
          pres.status = api.step.FAILURE
          pres.step_text = 'Failed to upload test results'

  elif location == common_pb2.PLATFORM_RENODE:
    cros_src_path = api.cros_source.workspace_path
    with api.step.nest('Upload Renode Firmware test results') as pres:
      for test_results in api.file.glob_paths(
          'renode results', cros_src_path, 'src/platform/ec/test_results.json'):
        try:
          rdb_cmd = [
              'vpython3', cros_src_path /
              'src/platform/ec/util/run_device_tests_to_resultdb.py',
              '--result=' + str(test_results), '--upload'
          ]
          base_variant = {'builder_name': builder_name}
          api.step('run', api.resultdb.wrap(rdb_cmd, base_variant=base_variant))

        except StepFailure:
          pres.status = api.step.FAILURE
          pres.step_text = 'Failed to upload test results'


def CreateContainers(api, config):
  with api.step.nest('Create test containers') as pres:
    try:
      if not (api.cros_infra_config.should_run(
          config.build.install_packages.run_spec) and
              api.build_menu.container_version):
        pres.step_text = 'Skipping due to missing builder configs.'
        return

      env_info = api.build_menu.setup_sysroot_and_determine_relevance()

      packages = env_info.packages

      api.build_menu.bootstrap_sysroot(config)
      if api.build_menu.install_packages(config=config, packages=packages):
        api.build_menu.create_containers(config)

    except StepFailure as e:
      pres.status = api.step.WARNING
      pres.step_text = 'Failed to create containers: ' + str(e)


def _extract_coverage_artifacts(completed_builds):
  results = []
  for b in completed_builds.values():
    if 'artifacts' not in b.output.properties:
      continue
    artifacts = b.output.properties['artifacts']
    gs_bucket = artifacts['gs_bucket'] if 'gs_bucket' in artifacts else None
    gs_path = artifacts['gs_path'] if 'gs_path' in artifacts else None
    if gs_bucket and gs_path:
      results.append((gs_bucket, gs_path, b.id))
  return results


def RunSteps(api, properties):
  with api.mutable_output.wrap():
    start_time = api.time.utcnow()
    commit = api.src_state.gitiles_commit
    if properties.gitiles_commit:
      commit = properties.gitiles_commit
    shard_count = properties.shard_count
    shard_index = properties.shard_index
    if shard_count > 1 and properties.bump_version:
      step_result = api.step('guard bump_version', cmd=None)
      step_result.presentation.status = api.step.FAILURE
      step_result.presentation.step_text = 'bump_version is not supported with shard_count > 1'
      raise api.step.StepFailure(
          'bump_version is not supported with shard_count > 1')

    if shard_count > 1 and not shard_index:
      with api.step.nest('schedule and wait for shards') as pres, \
           api.build_menu.configure_builder(commit=commit) as config:

        location = properties.firmware_location or config.general.firmware_location
        if properties.code_coverage and location != common_pb2.PLATFORM_ZEPHYR:
          raise api.step.StepFailure(
              'firmware_builder: coverage is only supported for PLATFORM_ZEPHYR'
          )

        requests = []
        builder = api.buildbucket.build.builder.builder
        bucket = api.buildbucket.build.builder.bucket

        for i in range(1, shard_count + 1):
          props = MessageToDict(properties, preserving_proto_field_name=True)

          props['shard_index'] = i

          props['shard_count'] = shard_count
          requests.append(
              api.buildbucket.schedule_request(
                  bucket=bucket, builder=builder, properties=props,
                  gerrit_changes=api.buildbucket.build.input.gerrit_changes,
                  gitiles_commit=api.buildbucket.build.input.gitiles_commit))

        builds = api.buildbucket.schedule(requests)

        # Wait for them and collect outputs
        completed_builds = api.buildbucket.collect_builds(
            [b.id for b in builds],
            step_name='collect shard builds',
            timeout=3600 * 2,
        )

        failed_ids = []
        for b in completed_builds.values():
          if b.status != bb_common_pb2.SUCCESS:
            failed_ids.append(str(b.id))

        if properties.code_coverage:
          # Setup workspace to use cros_sdk
          with api.build_menu.setup_workspace():
            chromiumos_sdk_version = _read_chromiumos_sdk_pin(api, properties)

            with api.step.nest('download shard coverage'):
              shards_dir = api.src_state.workspace_path.joinpath(
                  'src', 'platform', 'ec', 'zephyr', 'shards')
              api.file.ensure_directory('create shards dir', shards_dir)
              for gs_bucket, gs_path, build_id in _extract_coverage_artifacts(
                  completed_builds):
                api.gsutil.download(
                    gs_bucket,
                    f'{gs_path}/coverage.tbz2',
                    shards_dir.joinpath(f'{build_id}_coverage.tbz2'),
                    name=f'download shard {build_id}',
                )

            api.build_menu.setup_chroot(sdk_version=chromiumos_sdk_version)
            cmd = [
                './firmware_builder.py',
                'merge-shards',
                '--merge-dir',
                'shards',
            ]
            with api.context(
                cwd=api.src_state.workspace_path.joinpath(
                    'src', 'platform', 'ec', 'zephyr')):
              api.cros_sdk.run(
                  'merge coverage shards',
                  cmd,
              )

            coverage_tar = api.src_state.workspace_path.joinpath(
                'src', 'platform', 'ec', 'build', 'zephyr', 'coverage.tbz2')
            # Use the proper GS bucket and determine a unique path for this builder/run
            dest_bucket = (
                api.cros_infra_config.config.artifacts.artifacts_gs_bucket)
            base_artifacts_path = api.cros_artifacts.artifacts_gs_path(
                api.buildbucket.build.builder.builder,
                common_pb2.BuildTarget(name='coverage'),
            )
            dest_path = f'{base_artifacts_path}/coverage.tbz2'
            api.gsutil.upload(
                coverage_tar,
                dest_bucket,
                dest_path,
            )

        if failed_ids:
          pres.step_text = f'{len(failed_ids)} shards failed.'
          pres.status = api.step.FAILURE
          raise api.step.StepFailure(f"shards failed: {','.join(failed_ids)}")

        pres.step_text = 'All shards succeeded.'
      return result_pb2.RawResult(status=bb_common_pb2.SUCCESS)

    with api.failures.ignore_exceptions():
      with api.step.nest('checking attestation eligibility') as pres:
        # Config determines whether to report artifacts.
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('start')
          pres.step_text = f'{api.cros_infra_config.config.id.name} is attestation eligible'
        else:
          pres.step_text = f'{api.cros_infra_config.config.id.name} NOT attestation eligible'
    with api.build_menu.configure_builder(commit=commit) \
      as config, api.build_menu.setup_workspace():
      is_staging = api.cros_infra_config.is_staging
      if properties.bump_version:
        api.cros_version.bump_version(dry_run=is_staging)
        api.cros_release.create_buildspec(
            dry_run=is_staging, gs_location=properties.buildspec_gs_path)
      chromiumos_sdk_version = _read_chromiumos_sdk_pin(api, properties)
      api.build_menu.setup_chroot(sdk_version=chromiumos_sdk_version)
      api.cros_sdk.run('set ccache limit', ['ccache', '-M', '50G'])

      service = api.cros_build_api.FirmwareService
      chroot = api.cros_sdk.chroot
      location = properties.firmware_location or config.general.firmware_location

      with api.failures.ignore_exceptions():
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('compile')
      firmware_targets = [
          FirmwareTarget(name=bt.name) for bt in properties.build_targets
      ]
      build = api.buildbucket.build

      def _upload_artifacts(ignore_failure: bool = False):
        try:
          return api.build_menu.upload_artifacts(
              config=config, report_to_spike=api.cros_infra_config.config
              .artifacts.attestation_eligible, use_file_paths=True,
              build_targets=firmware_targets)
        except StepFailure as e:
          if ignore_failure:
            # Log upload failure but preserve the build/test exception.
            step_result = api.step('Upload artifacts failed (ignored)',
                                   cmd=None)
            step_result.presentation.status = api.step.WARNING
            step_result.presentation.step_text = "Upload failed on top of build/test failure"
            return None, None
          raise e

      # Inject shard arguments through the USE environment variable,
      # which safely propagates through the cros_sdk chroot boundary natively.
      use_env = {}
      if properties.shard_count > 1:
        use_env[
            'USE'] = f"%(USE)s shard_index_{properties.shard_index} shard_count_{properties.shard_count}"

      with api.context(env=use_env):
        try:
          response = service.BuildAllFirmware(
              BuildAllFirmwareRequest(
                  firmware_location=location,
                  chroot=chroot,
                  code_coverage=properties.code_coverage,
                  firmware_targets=firmware_targets,
                  avb_enabled=properties.avb_enabled,
              ),
              name="build firmware",
          )
        except StepFailure as e:
          _upload_artifacts(ignore_failure=True)
          raise e

        binary_sizes = {}
        if response.metrics and response.metrics.value:
          for fw_metric in response.metrics.value:
            region_prefix = ''
            if fw_metric.platform_name:
              region_prefix += fw_metric.platform_name + '_'
            if fw_metric.target_name:
              region_prefix += fw_metric.target_name + '_'
            for fw_section in fw_metric.fw_section:
              if fw_section.track_on_gerrit:
                if fw_section.used:
                  binary_sizes[region_prefix +
                               fw_section.region] = fw_section.used
                if fw_section.total:
                  binary_sizes[region_prefix + fw_section.region +
                               '.budget'] = fw_section.total

        if binary_sizes:
          api.easy.set_properties_step(binary_sizes=binary_sizes,
                                       step_name='output binary sizes')
        snapshot_sha = api.src_state.gitiles_commit.id
        api.easy.set_properties_step(got_revision=snapshot_sha,
                                     step_name='output got_revision')

        try:
          service.TestAllFirmware(
              TestAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                     code_coverage=properties.code_coverage,
                                     firmware_targets=firmware_targets,
                                     avb_enabled=properties.avb_enabled,
                                     toolchain=properties.toolchain),
              name='test firmware')
        except StepFailure as e:
          _upload_artifacts(ignore_failure=True)
          UploadTestResults(api, location, build.builder.builder)
          raise e

      uploaded_artifacts, artifact_dir = _upload_artifacts()
      published = collections.defaultdict(list)
      if uploaded_artifacts and uploaded_artifacts.published:
        published.update(uploaded_artifacts.published)

      # Read metadata jsonpb
      metadata_by_name = {}
      with api.step.nest('reading metadata') as step:
        step.logs['debug'] = ''
        for metadata_path in uploaded_artifacts.files_by_artifact.get(
            'FIRMWARE_TARBALL_INFO', []):
          # The real artifact_dir will be something like /b/s/w/ir/x/w/rc/artifactsp9n8vgbe
          metadata_path = api.path.abspath(
              api.path.join(artifact_dir, metadata_path))
          if api.path.exists(metadata_path):
            step.logs['debug'] += f'Reading proto from {metadata_path}\n'
            metadata = api.file.read_proto(
                'read fw metadata',
                metadata_path,
                FirmwareArtifactInfo,
                'JSONPB',
            )
            for obj in metadata.objects:
              step.logs[
                  'debug'] += f'metadata_by_name[{obj.file_name}]={obj.tarball_info}\n'
              metadata_by_name[obj.file_name] = obj.tarball_info
          else:
            step.logs['debug'] += f'{metadata_path} does not exist\n'

      # Publish files by board. Artifact types FIRMWARE_TARBALL,
      # FIRMWARE_TARBALL_INFO, and FIRMWARE_TOKEN_DATABASE get written to
      # gs://firmware-image-archive/{board}/{build.builder.builder}/{version}/artifact.
      # If the file has no boards, omit the board dir.

      if not api.cv.active:
        with api.step.nest('publish artifacts by board') as step:
          # Go through all the files, and group by board.
          artifacts_by_board = collections.defaultdict(
              lambda: collections.defaultdict(list))
          for artifact_type in uploaded_artifacts.files_by_artifact.keys():
            if artifact_type not in (
                'FIRMWARE_TARBALL',
                'FIRMWARE_TARBALL_INFO',
                'FIRMWARE_TOKEN_DATABASE',
            ):
              continue
            for artifact_name in uploaded_artifacts.files_by_artifact[
                artifact_type]:
              file_metadata = metadata_by_name.get(artifact_name)
              if file_metadata and file_metadata.board:
                for board in file_metadata.board:
                  artifacts_by_board[board][artifact_type].append(artifact_name)
              else:
                artifacts_by_board[None][artifact_type].append(artifact_name)

          version = api.cros_version.version
          publish_builder_name = build.builder.builder
          if publish_builder_name.endswith('-branch'):
            publish_builder_name = publish_builder_name[:-len('-branch')]
          gsutil_timeout_seconds = 15 * 60
          publish_bucket = "firmware-image-archive"
          if api.build_menu.is_staging:
            publish_bucket = 'staging-chromeos-image-archive'
          for (board, artifacts) in artifacts_by_board.items():
            if board:
              publish_loc = f'{publish_bucket}/{board}/{publish_builder_name}/{version.platform_version}'
            else:
              publish_loc = f'{publish_bucket}/{publish_builder_name}/{version.platform_version}'
            if board:
              link_name = f'gs publish dir: {board}'
            else:
              link_name = 'gs publish dir: NO BOARD'
            link_value = (
                'https://console.cloud.google.com/storage/browser/%s' %
                publish_loc)
            upload_uri = 'gs://%s/%s' % (uploaded_artifacts.gs_bucket,
                                         uploaded_artifacts.gs_path)
            step.links[link_name] = link_value
            for (aname, files) in artifacts.items():
              files = [x for x in files if x != '.']
              if files:
                publish_uri = 'gs://' + publish_loc
                if not publish_uri.endswith('/'):
                  publish_uri += '/'
                dir_to_files = collections.defaultdict(list)
                for path in files:
                  path_dir = os.path.dirname(path)
                  if path_dir:
                    path_dir += '/'
                  dir_to_files[path_dir].append(path)
                for publish_loc_suffix, files_in_group in dir_to_files.items():
                  cmd = ['cp', '-r']
                  cmd += [
                      '%s/%s' % (upload_uri, path) for path in files_in_group
                  ]
                  cmd.append(publish_uri + publish_loc_suffix)
                  max_retries = 3
                  for retries in range(max_retries):
                    try:
                      api.gsutil(cmd, multithreaded=True,
                                 timeout=gsutil_timeout_seconds)
                      break
                    except StepFailure as ex:
                      if ex.had_timeout and retries < max_retries - 1:
                        continue
                      raise
                published[aname].append({
                    'gs_location': publish_loc,
                    'files': files
                })

      with api.failures.ignore_exceptions():
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('upload-complete')

      # Invoke signing if applies.
      if _invoke_signing_for_current_build(build.builder.builder,
                                           uploaded_artifacts, properties):
        requests = []
        sign_image_props = MessageToDict(properties.sign_image_properties,
                                         preserving_proto_field_name=True)
        bucket = 'staging' if api.build_menu.is_staging else 'release'
        builder = 'staging-sign-image' if api.build_menu.is_staging else 'sign-image'

        # Legacy signing requests:
        with api.step.nest('schedule legacy signing build') as pres:
          pres.step_text = '\n'.join([
              f'builder_name={build.builder.builder}',
              f'signing_allowed_builder_names={properties.signing_allowed_builder_names}',
              f'sign_image_properties={properties.sign_image_properties}',
              f'uploaded_artifacts={uploaded_artifacts}',
          ])
          for artifact_name in uploaded_artifacts.files_by_artifact[
              'FIRMWARE_TARBALL']:
            archive = 'gs://%s/%s/%s' % (uploaded_artifacts.gs_bucket,
                                         uploaded_artifacts.gs_path,
                                         artifact_name)
            sign_image_props['archive'] = archive
            requests.append(
                api.buildbucket.schedule_request(bucket=bucket, builder=builder,
                                                 properties=sign_image_props))

          api.buildbucket.schedule(requests)

      # Publish tar files to pubsub.
      if not api.cv.active:
        with api.step.nest('sending pub/sub notifications') as step:
          step.logs['debug'] = ''
          api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_FIRMWARE,
                                             None)
          branch = api.src_state.gitiles_commit.ref
          if branch.startswith('refs/heads/'):
            branch = branch[len('refs/heads/'):]
          bcs_version = api.cros_version.version
          step.logs['uploaded_artifacts'] = str(uploaded_artifacts)
          step.logs[
              'debug'] += 'Checking uploaded_artifacts for FIRMWARE_TARBALL_INFO\n'
          if published:
            for atype, dests in published.items():
              step.logs['debug'] += f'published: {atype}:{dests}\n'
              for loc in dests:
                for file in loc['files']:
                  metadata = metadata_by_name.get(file)
                  step.logs[
                      'debug'] += f'{file} was published to {loc["gs_location"]} metadata={metadata}\n'
                  if metadata:
                    for board in metadata.board:
                      if metadata.type == FirmwareArtifactInfo.TarballInfo.FirmwareType.EC and branch == 'snapshot':
                        step.logs[
                            'debug'] += f'SKIPPING Pub/sub {file} for {board}\n'
                        continue
                      step.logs['debug'] += f'Pub/sub {file} for {board}\n'
                      api.build_reporting.reset_build_report(board)
                      build_report = api.build_reporting.merged_build_report
                      step_info = build_report.steps.info[
                          api.build_reporting.step_as_str(
                              BuildReport.StepDetails.STEP_OVERALL)]
                      step_info.order = 1
                      step_info.status = BuildReport.StepDetails.STATUS_SUCCESS
                      step_info.runtime.begin.FromDatetime(start_time)
                      step_info.runtime.end.FromDatetime(api.time.utcnow())
                      build_report.status.value = BuildReport.BuildStatus.SUCCESS
                      build_config = build_report.config
                      build_config.branch.name = branch
                      new_ver = build_config.versions.add()
                      new_ver.kind = BuildReport.BuildConfig.VERSION_KIND_MILESTONE
                      new_ver.value = str(bcs_version.milestone)
                      new_ver = build_config.versions.add()
                      new_ver.kind = BuildReport.BuildConfig.VERSION_KIND_PLATFORM
                      new_ver.value = bcs_version.platform_version
                      gs_bucket, gs_path = loc['gs_location'].split('/', 1)
                      api.build_reporting.publish_build_artifacts(
                          UploadedArtifacts(gs_bucket, gs_path,
                                            {atype: [file]}), artifact_dir,
                          force_publish=metadata.publish_to_goldeneye)


      UploadTestResults(api, location, build.builder.builder)

      CreateContainers(api, config)

      api.easy.set_properties_step(
          suite_scheduling=str(properties.set_suite_scheduling and
                               not is_staging))


def _read_chromiumos_sdk_pin(api, properties):
  if properties.chromiumos_sdk_pin_file:
    with api.step.nest('read chromiumos-sdk pin'):
      filepath = api.src_state.workspace_path.joinpath(
          properties.chromiumos_sdk_pin_file)
      return api.file.read_text('read {}'.format(filepath), filepath).strip()
  return None


def _invoke_signing_for_current_build(builder_name, uploaded_artifacts,
                                      properties):
  """
  Whether signing for current build should be invoked.

  Args:
    builder_name (str): Current builder name.
    uploaded_artifacts (UploadedArtifacts): Uploaded artifacts.
    properties (BuildFirmwareProperties): Build firmware properties for current build.

  Returns:
    (bool): True if signing should be invoked. False otherwise.
  """
  valid_builder = builder_name in properties.signing_allowed_builder_names and properties.sign_image_properties
  artifact_upload_succeeded = uploaded_artifacts and len(uploaded_artifacts) > 2
  return valid_builder and artifact_upload_succeeded


def GenTests(api):

  ZEPHYR_ARTIFACTS = '''{
  "artifacts": {
    "artifacts": [
      {
        "artifactType": 31,
        "location": 2,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/firmware_metadata.jsonpb"
          }
        ]
      },
      {
        "artifactType": 30,
        "location": 2,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/brox.EC.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/brox.EC_elf.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/karis.EC.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/karis.EC_elf.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/screebo.EC.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/screebo.EC_elf.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/brox/firmware_from_source.tar.bz2"
          },
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/rex/firmware_from_source.tar.bz2"
          }
        ]
      },
      {
        "artifactType": 55,
        "location": 2,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/tokens.bin"
          }
        ]
      }
    ]
  }
}'''
  ZEPHYR_METADATA = FirmwareArtifactInfo(objects=[
      FirmwareArtifactInfo.ObjectInfo(
          file_name='brox.EC.tar.bz2', tarball_info=FirmwareArtifactInfo
          .TarballInfo(type='EC', board=['brox'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='brox.EC_elf.tar.bz2', tarball_info=FirmwareArtifactInfo
          .TarballInfo(type='EC', board=['brox'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='karis.EC.tar.bz2', tarball_info=FirmwareArtifactInfo
          .TarballInfo(type='EC', board=['rex'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='karis.EC_elf.tar.bz2', tarball_info=FirmwareArtifactInfo
          .TarballInfo(type='EC', board=['rex'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='screebo.EC.tar.bz2', tarball_info=FirmwareArtifactInfo
          .TarballInfo(type='EC', board=['rex'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='screebo.EC_elf.tar.bz2', tarball_info=FirmwareArtifactInfo
          .TarballInfo(type='EC', board=['rex'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='brox/firmware_from_source.tar.bz2',
          tarball_info=FirmwareArtifactInfo.TarballInfo(type='EC',
                                                        board=['brox'])),
      FirmwareArtifactInfo.ObjectInfo(
          file_name='rex/firmware_from_source.tar.bz2',
          tarball_info=FirmwareArtifactInfo.TarballInfo(type='EC',
                                                        board=['rex'])),
  ])

  def get_signing_image_props_for_test(is_staging=False):
    """
    Get SignImageProperties for test.

    Args:
      is_staging (bool): Whether properties need for staging.

    Returns:
      (dict): SignImageProperties object as dict for testing.
    """
    return {
        'image_type': 13,
        'channel': 0,
        'keyset': 'test-keyset',
        'signer_type': 2 if is_staging else 1,
        'allow_non_release_signer_bucket': True,
        'gsc_instructions': {
            'target': 1,
        },
    }

  def test(name, *args, **kwargs):
    version_str = kwargs.pop('version', 'R99-1234.56.0')
    version = api.cros_version.workspace_version(version_str)
    status = kwargs.pop('status', 'SUCCESS')
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('input_properties', {'firmware_location': 1})
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, version, *args, status=status)

  yield test(
      'fw-coverage-fails-non-zephyr',
      builder='fw-ec-cq',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_EC,
          'code_coverage': True,
          'shard_count': 2,
          'shard_index': 0,
      },
      status='FAILURE',
  )

  yield test(
      'postsubmit',
      api.post_check(post_process.DoesNotRun, 'snoop: report_stage'),
  )

  yield test('cq', api.post_check(post_process.DoesNotRun,
                                  'snoop: report_stage'), cq=True, dry_run=True,
             builder='fw-ec-cq')

  yield test(
      'firmware-zephyr-cq',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      # CQ runs should not send pub/sub.
      api.post_check(
          post_process.DoesNotRun,
          'sending pub/sub notifications.publish artifacts to pubsub'),
      cq=True,
      dry_run=True,
      builder='firmware-zephyr-cq',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'bump_version': False,
          'set_suite_scheduling': True,
          'avb_enabled': True,
          'toolchain': 'host/gnu',
      })

  yield test(
      'firmware-zephyr-postsubmit',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data('reading metadata.read fw metadata',
                    api.file.read_proto(ZEPHYR_METADATA)),
      # TODO(b/358654822): When DLM can handle multiple artifacts per version, revisit this.
      api.post_check(
          post_process.DoesNotRun,
          'sending pub/sub notifications.publish artifacts to pubsub'),
      builder='firmware-zephyr-postsubmit',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'bump_version': False,
          'set_suite_scheduling': True,
          'avb_enabled': False,
      })

  yield test(
      'fw-branch-postsubmit',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data('reading metadata.read fw metadata',
                    api.file.read_proto(ZEPHYR_METADATA)),
      # TODO(b/358654822): When DLM can handle multiple artifacts per version, revisit this.
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub.build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (2).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (3).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (4).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (5).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (6).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogContains,
          'sending pub/sub notifications.publish artifacts to pubsub (7).build status pubsub update',
          'message', [
              'artifacts',
              'gs://firmware-image-archive/firmware-R126-15885.B/1234.56.0/brox/firmware_from_source.tar.bz2'
          ]),
      api.post_check(
          post_process.LogContains,
          'sending pub/sub notifications.publish artifacts to pubsub (8).build status pubsub update',
          'message', [
              'artifacts',
              'gs://firmware-image-archive/firmware-R126-15885.B/1234.56.0/rex/firmware_from_source.tar.bz2'
          ]),
      builder='firmware-R126-15885.B-branch',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'attestation_eligible': True,
          'buildspec_gs_path': 'gs://chromeos-manifest-versions/buildspecs/',
          'bump_version': True,
          'gitiles_commit': {
              'host': 'chrome-internal.googlesource.com',
              'project': 'chromeos/manifest-internal',
              'ref': 'refs/heads/firmware-R126-15885.B',
          },
          'set_suite_scheduling': True,
      },
  )

  yield test(
      'ec-branch-postsubmit',
      api.cros_infra_config.override_builder_configs_test_data(
          json_format.Parse(
              """{
  "builderConfigs": [
    {
      "artifacts": {
        "artifactsGsBucket": "chromeos-image-archive",
        "artifactsInfo": {
          "firmware": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "FIRMWARE_TARBALL",
                  "FIRMWARE_TARBALL_INFO",
                  "FIRMWARE_TOKEN_DATABASE"
                ]
              }
            ]
          }
        },
        "prebuilts": "PRIVATE",
        "prebuiltsGsBucket": "chromeos-prebuilt"
      },
      "general": {
        "firmwareLocation": "PLATFORM_ZEPHYR"
      },
      "id": {
        "bucket": "firmware",
        "name": "firmware-R126-15886.2.B-branch",
        "type": "POSTSUBMIT"
      }
    }
  ]
}""", BuilderConfigs()), step_name='checking attestation eligibility'),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data('reading metadata.read fw metadata',
                    api.file.read_proto(ZEPHYR_METADATA)),
      # TODO(b/358654822): When DLM can handle multiple artifacts per version, revisit this.
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub.build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (2).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogContains,
          'sending pub/sub notifications.publish artifacts to pubsub (3).build status pubsub update',
          'message', [
              'artifacts',
              'gs://firmware-image-archive/brox/firmware-R126-15886.2.B/1234.56.0/brox/firmware_from_source.tar.bz2'
          ]),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (4).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (5).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogContains,
          'sending pub/sub notifications.publish artifacts to pubsub (6).build status pubsub update',
          'message', [
              'artifacts',
              'gs://firmware-image-archive/rex/firmware-R126-15886.2.B/1234.56.0/rex/firmware_from_source.tar.bz2'
          ]),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (7).build status pubsub update',
          'message', ['artifacts']),
      api.post_check(
          post_process.LogDoesNotContain,
          'sending pub/sub notifications.publish artifacts to pubsub (8).build status pubsub update',
          'message', ['artifacts']),
      builder='firmware-R126-15886.2.B-branch',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'attestation_eligible': True,
          'buildspec_gs_path': 'gs://chromeos-manifest-versions/buildspecs/',
          'bump_version': True,
          'gitiles_commit': {
              'host': 'chrome-internal.googlesource.com',
              'project': 'chromeos/manifest-internal',
              'ref': 'refs/heads/firmware-R126-15886.2.B',
          },
          'set_suite_scheduling': True,
      },
  )

  # A test that is as real as possible. Copied from go/bbid/8682355855772186353
  # Config lives in recipe_modules/cros_infra_config/test_builder_configs.json
  # not here.
  yield test(
      'firmware-ec-R148-16640.2.B-branch',
      api.cros_infra_config.override_builder_configs_test_data(
          json_format.Parse(
              """{
  "builderConfigs": [
    {
      "id": {
        "name": "firmware-ec-R148-16640.2.B-branch",
        "type": "POSTSUBMIT",
        "bucket": "firmware"
      },
      "general": {
        "critical": true,
        "environment": "PRODUCTION",
        "runWhen": {
          "mode": "ALWAYS_RUN"
        },
        "sdkCacheVersion": 1,
        "manifest": "PRIVATE",
        "firmwareLocation": "PLATFORM_ZEPHYR",
        "publishImageSizes": true
      },
      "artifacts": {
        "prebuilts": "NONE",
        "artifactsGsBucket": "chromeos-image-archive",
        "artifactsInfo": {
          "toolchain": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "CLANG_CRASH_DIAGNOSES"
                ]
              }
            ]
          },
          "image": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "DLC_IMAGE"
                ]
              },
              {
                "artifactTypes": [
                  "LICENSE_CREDITS"
                ]
              }
            ]
          },
          "sysroot": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "DEBUG_SYMBOLS"
                ]
              },
              {
                "artifactTypes": [
                  "BREAKPAD_DEBUG_SYMBOLS"
                ]
              }
            ]
          },
          "firmware": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "FIRMWARE_TARBALL",
                  "FIRMWARE_TARBALL_INFO",
                  "FIRMWARE_TOKEN_DATABASE"
                ],
                "location": "PLATFORM_ZEPHYR"
              }
            ]
          }
        },
        "attestationEligible": true
      },
      "chrome": {
        "internal": true
      },
      "build": {
        "useFlags": [
          {
            "flag": "chrome_internal"
          }
        ],
        "sdkUpdate": {
          "sdkUpdateRunSpec": "NO_RUN"
        },
        "installPackages": {
          "disableGoma": true,
          "dependencies": "ALL_DEPENDENCIES"
        }
      },
      "unitTests": {
        "ebuildsRunSpec": "RUN",
        "dependencies": "ALL_DEPENDENCIES"
      },
      "updateChroot": {
        "runSpec": "NO_RUN"
      }
    }
  ]
}""", BuilderConfigs()), step_name='checking attestation eligibility'),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          (Path(__file__).parent.resolve() /
           'firmware_test_r148_zephyr_artifacts.json').read_text()),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data(
          'reading metadata.read fw metadata',
          api.file.read_proto(
              json_format.Parse(
                  (Path(__file__).parent.resolve() /
                   'firmware_test_r148_zephyr_metadata.jsonpb').read_text(),
                  FirmwareArtifactInfo(), ignore_unknown_fields=True))),
      version='R148-16640.2.39',
      builder='firmware-ec-R148-16640.2.B-branch',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'attestation_eligible': True,
          'avb_enabled': False,
          'buildspec_gs_path': 'gs://chromeos-manifest-versions/buildspecs/',
          'bump_version': False,
          'gitiles_commit': {
              'host': 'chrome-internal.googlesource.com',
              'project': 'chromeos/manifest-internal',
              'ref': 'refs/heads/firmware-R148-16640.2.B',
          },
          'set_suite_scheduling': True,
      },
  )

  sdk_pin_path = 'src/platform/foobar/sdk-version'
  yield test(
      'cq-sdk-pin',
      api.step_data(
          'read chromiumos-sdk pin.read [CLEANUP]/chromiumos_workspace/{}'
          .format(sdk_pin_path), api.file.read_text('2022.01.20.073008\n')),
      api.post_check(post_process.DoesNotRun,
                     'configure builder.cros_infra_config.gitiles-fetch-ref'),
      cq=True,
      dry_run=True,
      builder='fw-ec-cq',
      input_properties={
          'firmware_location': 3,
          'chromiumos_sdk_pin_file': sdk_pin_path,
      },
  )

  yield test(
      'upload-fail',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1),
      status='INFRA_FAILURE',
  )

  yield test(
      'working-upload-fail',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1),
      api.post_check(post_process.DoesNotRun, 'schedule legacy signing build'),
      input_properties=({
          'firmware_location': 1
      }),
      status='INFRA_FAILURE',
  )

  yield test(
      'fw-test-fail',
      api.step_data('test firmware.call build API script', retcode=1),
      api.post_check(post_process.MustRun, 'Upload EC Firmware test results'),
      input_properties=({
          'firmware_location': common_pb2.PLATFORM_ZEPHYR
      }),
      status='FAILURE',
  )

  yield test(
      'upload-test-results-fail',
      api.step_data('Upload EC Firmware test results.run', retcode=1),
      api.post_check(
          post_process.StepTextContains,
          'Upload EC Firmware test results',
          ['Failed to upload test results'],
      ),
      api.post_check(post_process.StepFailure,
                     'Upload EC Firmware test results.run'), input_properties=({
                         'firmware_location': common_pb2.PLATFORM_ZEPHYR
                     }))

  yield test(
      'upload-renode-test-results-fail',
      api.step_data('Upload Renode Firmware test results.renode results',
                    api.file.glob_paths(['src/platform/ec/test_results.json'])),
      api.step_data('Upload Renode Firmware test results.run', retcode=1),
      api.post_check(
          post_process.StepTextContains,
          'Upload Renode Firmware test results',
          ['Failed to upload test results'],
      ),
      api.post_check(post_process.StepFailure,
                     'Upload Renode Firmware test results.run'),
      input_properties=({
          'firmware_location': common_pb2.PLATFORM_RENODE
      }))

  yield test(
      'signing-invocation',
      api.post_check(post_process.MustRun, 'schedule legacy signing build'),
      builder='fw-ec-postsubmit', input_properties={
          'firmware_location': 1,
          'signing_allowed_builder_names': ['fw-ec-postsubmit'],
          'sign_image_properties': get_signing_image_props_for_test(),
      })

  yield test(
      'staging-signing-invocation',
      api.post_check(post_process.MustRun, 'schedule legacy signing build'),
      builder='fw-ec-postsubmit', bucket='staging', input_properties={
          'firmware_location':
              1,
          'signing_allowed_builder_names': ['fw-ec-postsubmit'],
          'sign_image_properties':
              get_signing_image_props_for_test(is_staging=True),
      })

  yield test('output-binary-sizes',
             api.post_check(post_process.MustRun, 'output binary sizes'),
             api.post_check(post_process.MustRun, 'output got_revision'))

  yield test(
      'create test containers',
      api.post_check(
          post_process.MustRun,
          'Create test containers.create test service containers.upload container metadata.gsutil upload'
      ), builder='amd64-generic-snapshot', input_properties={
          '$chromeos/build_menu': {
              'build_target': {
                  'name': 'amd64-generic',
              },
              'container_version_format':
                  '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }
      })

  yield test(
      'create test containers exception',
      api.step_data(
          'Create test containers.call chromite.api.PackageService/GetTargetVersions.call build API script',
          retcode=1),
      api.post_check(
          post_process.DoesNotRun,
          'Create test containers.create test service containers.upload container metadata.gsutil upload'
      ),
      api.post_check(post_process.StepTextContains, 'Create test containers',
                     ['Failed to create containers']),
      builder='amd64-generic-snapshot', input_properties={
          '$chromeos/build_menu': {
              'build_target': {
                  'name': 'amd64-generic',
              },
              'container_version_format':
                  '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }
      })

  yield test(
      'gsutil-publish-timeout-retry-success',
      api.cros_infra_config.override_builder_configs_test_data(
          json_format.Parse(
              """{
  "builderConfigs": [
    {
      "artifacts": {
        "artifactsGsBucket": "chromeos-image-archive",
        "artifactsInfo": {
          "firmware": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "FIRMWARE_TARBALL",
                  "FIRMWARE_TARBALL_INFO",
                  "FIRMWARE_TOKEN_DATABASE"
                ]
              }
            ]
          }
        },
        "prebuilts": "PRIVATE",
        "prebuiltsGsBucket": "chromeos-prebuilt"
      },
      "general": {
        "firmwareLocation": "PLATFORM_ZEPHYR"
      },
      "id": {
        "bucket": "firmware",
        "name": "firmware-R126-15886.2.B-branch",
        "type": "POSTSUBMIT"
      }
    }
  ]
}""", BuilderConfigs()), step_name='checking attestation eligibility'),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data('reading metadata.read fw metadata',
                    api.file.read_proto(ZEPHYR_METADATA)),
      api.step_data('publish artifacts by board.gsutil cp',
                    times_out_after=901),
      builder='firmware-R126-15886.2.B-branch',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'attestation_eligible': True,
          'buildspec_gs_path': 'gs://chromeos-manifest-versions/buildspecs/',
          'bump_version': True,
          'gitiles_commit': {
              'host': 'chrome-internal.googlesource.com',
              'project': 'chromeos/manifest-internal',
              'ref': 'refs/heads/firmware-R126-15886.2.B',
          },
          'set_suite_scheduling': True,
      },
  )

  yield test(
      'gsutil-publish-timeout-retry-fail',
      api.cros_infra_config.override_builder_configs_test_data(
          json_format.Parse(
              """{
  "builderConfigs": [
    {
      "artifacts": {
        "artifactsGsBucket": "chromeos-image-archive",
        "artifactsInfo": {
          "firmware": {
            "outputArtifacts": [
              {
                "artifactTypes": [
                  "FIRMWARE_TARBALL",
                  "FIRMWARE_TARBALL_INFO",
                  "FIRMWARE_TOKEN_DATABASE"
                ]
              }
            ]
          }
        },
        "prebuilts": "PRIVATE",
        "prebuiltsGsBucket": "chromeos-prebuilt"
      },
      "general": {
        "firmwareLocation": "PLATFORM_ZEPHYR"
      },
      "id": {
        "bucket": "firmware",
        "name": "firmware-R126-15886.2.B-branch",
        "type": "POSTSUBMIT"
      }
    }
  ]
}""", BuilderConfigs()), step_name='checking attestation eligibility'),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data('reading metadata.read fw metadata',
                    api.file.read_proto(ZEPHYR_METADATA)),
      api.step_data('publish artifacts by board.gsutil cp',
                    times_out_after=901),
      api.step_data('publish artifacts by board.gsutil cp (2)',
                    times_out_after=901),
      api.step_data('publish artifacts by board.gsutil cp (3)',
                    times_out_after=901),
      builder='firmware-R126-15886.2.B-branch',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'attestation_eligible': True,
          'buildspec_gs_path': 'gs://chromeos-manifest-versions/buildspecs/',
          'bump_version': True,
          'gitiles_commit': {
              'host': 'chrome-internal.googlesource.com',
              'project': 'chromeos/manifest-internal',
              'ref': 'refs/heads/firmware-R126-15886.2.B',
          },
          'set_suite_scheduling': True,
      },
      status='INFRA_FAILURE',
  )

  yield test(
      'build-and-upload-fail',
      api.step_data('build firmware.call build API script', retcode=1),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1),
      api.post_check(post_process.MustRun, 'build firmware'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.MustRun, 'Upload artifacts failed (ignored)'),
      api.post_check(post_process.DoesNotRun, 'publish artifacts by board'),
      api.post_check(post_process.DoesNotRun, 'schedule legacy signing build'),
      api.post_check(post_process.DoesNotRun, 'sending pub/sub notifications'),
      status='FAILURE',
  )

  b1 = api.buildbucket.ci_build_message(build_id=123, status="SUCCESS")
  b3 = api.buildbucket.ci_build_message(build_id=125, status="SUCCESS")
  b4 = api.buildbucket.ci_build_message(build_id=126, status="SUCCESS")
  artifacts1 = struct_pb2.Struct()
  artifacts1.update({"gs_bucket": "my-bucket", "gs_path": "my-path"})
  b1.output.properties.update({"artifacts": artifacts1})

  b2 = api.buildbucket.ci_build_message(build_id=124, status="SUCCESS")
  artifacts2 = struct_pb2.Struct()
  artifacts2.update({"gs_bucket": "my-bucket", "gs_path": "my-path"})
  b2.output.properties.update({"artifacts": artifacts2})

  b_fail = api.buildbucket.ci_build_message(build_id=125, status="FAILURE")
  b_miss = api.buildbucket.ci_build_message(build_id=130, status="SUCCESS")
  b_miss.output.properties.update({"artifacts": {}})

  yield test(
      "dynamic-shard-missing-artifacts",
      api.post_check(
          post_process.DoesNotRun,
          "configure builder.cros_infra_config.gitiles-fetch-ref",
      ),
      api.buildbucket.simulated_collect_output(
          [b_miss],
          step_name="schedule and wait for shards.collect shard builds",
      ),
      cq=True,
      dry_run=True,
      builder="fw-ec-cq",
      input_properties={
          "firmware_location": 2,
          "code_coverage": True,
          "chromiumos_sdk_pin_file": sdk_pin_path,
          "shard_count": 2,
          "shard_index": 0,
      },
  )

  yield test(
      "dynamic-shard-worker",
      api.post_check(
          post_process.DoesNotRun,
          "configure builder.cros_infra_config.gitiles-fetch-ref",
      ),
      cq=True,
      dry_run=True,
      builder="fw-ec-cq",
      input_properties={
          "firmware_location": 2,
          "code_coverage": True,
          "chromiumos_sdk_pin_file": sdk_pin_path,
          "shard_count": 2,
          "shard_index": 1,
      },
  )

  yield test(
      "dynamic-shard-fanout",
      api.post_check(
          post_process.DoesNotRun,
          "configure builder.cros_infra_config.gitiles-fetch-ref",
      ),
      api.buildbucket.simulated_collect_output(
          [b1, b2, b3, b4],
          step_name="schedule and wait for shards.collect shard builds",
      ),
      cq=True,
      dry_run=True,
      builder="fw-ec-cq",
      input_properties={
          "firmware_location": 2,
          "code_coverage": True,
          "chromiumos_sdk_pin_file": sdk_pin_path,
          "shard_count": 2,
          "shard_index": 0,
      },
  )

  yield test(
      "sharding-with-bump-version-fails",
      api.post_check(post_process.StatusFailure),
      api.post_check(post_process.SummaryMarkdownRE,
                     ".*bump_version is not supported.*"),
      api.post_check(post_process.DropExpectation),
      input_properties={
          "firmware_location": 2,
          "code_coverage": True,
          "bump_version": True,
          "shard_count": 2,
          "shard_index": 1,
      },
      status="FAILURE",
  )

  yield test(
      "dynamic-shard-fanout-failure",
      api.post_check(
          post_process.DoesNotRun,
          "configure builder.cros_infra_config.gitiles-fetch-ref",
      ),
      api.buildbucket.simulated_collect_output(
          [b_fail],
          step_name="schedule and wait for shards.collect shard builds",
      ),
      cq=True,
      dry_run=True,
      builder="fw-ec-cq",
      input_properties={
          "firmware_location": 2,
          "code_coverage": True,
          "chromiumos_sdk_pin_file": sdk_pin_path,
          "shard_count": 2,
          "shard_index": 0,
      },
      status="FAILURE",
  )
