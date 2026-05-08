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
import re
import os
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import Parse as JsonToProto

import PB.chromiumos.common as common_pb2
from PB.chromite.api.firmware import BuildAllFirmwareRequest, FirmwareTarget
from PB.chromite.api.firmware import FirmwareArtifactInfo
from PB.chromite.api.firmware import TestAllFirmwareRequest
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.signing import BuildTargetSigningConfigs, BuildTargetSigningConfig, SigningConfig
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/bcid_reporter',
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

# Artifacts that don't need to be signed via legacy signing.
# `host_emulation` (and `he`) will never need to be signed.
# `nuvotitan_cw310_a1 fpga` will never need to be signed.
# `opentitan` (and `nt`) will need to be signed in the future, but signing
# isn't set up for that target yet.
SKIP_LEGACY_SIGNING_RE = re.compile(
    r'^(host_emulation|he|opentitan|nt|nuvotitan_cw310)-')
INCLUDE_SIGNING_RE = re.compile(r'nt-(ti50|system_test_auto)')
GENERATE_PAOS_RE = re.compile(r'nt-(perso|ti50)')


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


def RunSteps(api, properties):
  with api.mutable_output.wrap():
    start_time = api.time.utcnow()
    commit = api.src_state.gitiles_commit
    if properties.gitiles_commit:
      commit = properties.gitiles_commit
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

      service = api.cros_build_api.FirmwareService
      chroot = api.cros_sdk.chroot
      location = properties.firmware_location or config.general.firmware_location

      with api.failures.ignore_exceptions():
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('compile')
      firmware_targets = [
          FirmwareTarget(name=bt.name) for bt in properties.build_targets
      ]
      response = service.BuildAllFirmware(
          BuildAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                  code_coverage=properties.code_coverage,
                                  firmware_targets=firmware_targets,
                                  avb_enabled=properties.avb_enabled),
          name='build firmware')
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

      build = api.buildbucket.build
      try:
        service.TestAllFirmware(
            TestAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                   code_coverage=properties.code_coverage,
                                   firmware_targets=firmware_targets,
                                   avb_enabled=properties.avb_enabled),
            name='test firmware')
      except StepFailure as ex:
        UploadTestResults(api, location, build.builder.builder)
        raise ex

      uploaded_artifacts, artifact_dir = api.build_menu.upload_artifacts(
          config=config, report_to_spike=api.cros_infra_config.config.artifacts
          .attestation_eligible, use_file_paths=True,
          build_targets=firmware_targets)

      with api.failures.ignore_exceptions():
        if api.cros_infra_config.config.artifacts.attestation_eligible:
          api.bcid_reporter.report_stage('upload-complete')

      # Invoke signing if applies.
      signing_scheduled = False
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
          for artifact_name in [
              a
              for a in uploaded_artifacts.files_by_artifact['FIRMWARE_TARBALL']
              if not SKIP_LEGACY_SIGNING_RE.match(a)
          ]:
            archive = 'gs://%s/%s/%s' % (uploaded_artifacts.gs_bucket,
                                         uploaded_artifacts.gs_path,
                                         artifact_name)
            sign_image_props['archive'] = archive
            requests.append(
                api.buildbucket.schedule_request(bucket=bucket, builder=builder,
                                                 properties=sign_image_props))

          api.buildbucket.schedule(requests)
          signing_scheduled = True
        # Signing requests:
        with api.step.nest('sign artifacts'):
          signing_configs = []
          for artifact_name in [
              a
              for a in uploaded_artifacts.files_by_artifact['FIRMWARE_TARBALL']
              if INCLUDE_SIGNING_RE.match(a)
          ]:
            signing_configs.append(
                SigningConfig(
                    image_type=common_pb2.IMAGE_TYPE_GSC_FIRMWARE,
                    ensure_no_password=True,
                    archive_path=artifact_name,
                    channel=common_pb2.CHANNEL_AGNOSTIC,
                    output_names=[
                        f"@CHIP@_@KEYSET_VER@_{artifact_name.removesuffix('.tar.bz2')}"
                    ],
                ))

          # Set up the custom version number to indicate Ti50.
          version = api.cros_version.version
          api.signing_utils.custom_artifact_version = f'ti50/nt-signed/{version}'
          api.signing.signing_operation(
              config=BuildTargetSigningConfigs(build_target_signing_configs=[
                  BuildTargetSigningConfig(
                      keyset=properties.signing_keyset,
                      version=version.platform_version,
                      signing_configs=signing_configs,
                  )
              ]),
              local_artifact_dir=artifact_dir,
          )
          signing_scheduled = True

      if properties.pao_signing_config.key and uploaded_artifacts and len(
          uploaded_artifacts) > 2:
        with api.step.nest("signing PAOs in artifact"):
          with api.deferrals.raise_exceptions_at_end():
            for artifact_name in [
                a for a in
                uploaded_artifacts.files_by_artifact['FIRMWARE_TARBALL']
                if GENERATE_PAOS_RE.match(a)
            ]:
              with api.deferrals.defer_exceptions():
                api.signing.sign_ti50_paos(
                    artifact_dir, properties.pao_signing_config.project,
                    properties.pao_signing_config.keyring,
                    properties.pao_signing_config.key, artifact_name)

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
          metadata_by_name = {}
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
          if uploaded_artifacts.published:
            for atype, dests in uploaded_artifacts.published.items():
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

      # Tast artifacts are only required by ToT builders since those are the only
      # builders that generate signed outputs.
      # Ideally we would have an ArtifactType and key off of that.
      if location == common_pb2.PLATFORM_TI50 and signing_scheduled:
        CreateTi50TastArtifacts(api, config)

      api.easy.set_properties_step(
          suite_scheduling=str(properties.set_suite_scheduling and
                               not is_staging))


def CreateTi50TastArtifacts(api, config):
  """Create directories and files of artifacts needed by Ti50 Tast tests."""
  with api.step.nest('Create Ti50 Tast artifacts'):

    artifacts_gs_bucket = config.artifacts.artifacts_gs_bucket
    artifacts_gs_path = _artifacts_gs_path(api, config)

    tars = _find_files_with_suffix(api, artifacts_gs_bucket, artifacts_gs_path,
                                   '.tar.bz2')
    if len(tars) == 0:
      return

    temp_dir = api.path.mkdtemp()
    tast_dir = api.path.join(temp_dir, 'tast')
    tast_dir_empty = True
    download_dir = api.path.join(temp_dir, 'download')
    api.file.ensure_directory('Create download directory', download_dir)
    for tar_file in tars:
      api.gsutil.download(artifacts_gs_bucket, tar_file, download_dir,
                          name='download tarfile')
      base = os.path.basename(tar_file)
      downloaded_file = os.path.join(download_dir, base)
      parts = base[:-len('.tar.bz2')].split('-')
      board = parts[0]
      image = '-'.join(parts[1:])
      # andreiboard tarballs are the default, they don't have a board prefix.
      if image == '':
        image = board
        board = 'andreiboard'
      tast_subdir = os.path.join(tast_dir, '-'.join((board, image)))
      # Extract image binary and opentitantool config json files into tast_subdir
      with api.step.nest('Extract archive') as presentation:
        try:
          api.step('untar', [
              'tar', '-x', '--exclude=*_key*', '--wildcards',
              '*opentitantool_*.json', '--wildcards', '*.bin',
              r'--xform=s=^.*/\([^/]*\)$=\1=', '--one-top-level=' + tast_subdir,
              '-f', downloaded_file
          ])
          tast_dir_empty = False
        except api.step.StepFailure:
          presentation.step_text = 'No interesting files in archive.'
    if not tast_dir_empty:
      api.gsutil.upload(tast_dir, artifacts_gs_bucket, artifacts_gs_path,
                        ['-r'])


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


def _artifacts_gs_path(api, config):
  """The artifacts gs path given the builder config"""
  # target won't be used to construct the artifacts_gs_path since only using
  # gs_path in the template but it needs to be provided to avoid a crash
  target = collections.namedtuple('target', 'name')(name='')
  return api.cros_artifacts.artifacts_gs_path(config.id.name, target,
                                              config.id.type,
                                              template='{gs_path}')


def _find_files_with_suffix(api, bucket, path, suffix):
  """Find files ending in <suffix> in gs://<bucket>/<path>"""
  bucket_part = 'gs://{}/'.format(bucket)
  paths = []
  try:
    list_out = api.gsutil.list(bucket_part + path + '/**/*' + suffix, ['-r'],
                               stdout=api.raw_io.output_text())

    paths = list_out.stdout.splitlines()
  except api.step.InfraFailure:
    pass

  return [p.strip()[len(bucket_part):] for p in paths]


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

  TI50_ARTIFACTS = '''{
  "artifacts": {
    "artifacts": [
      {
        "artifactType": 31,
        "location": 3,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/firmware_metadata.jsonpb"
          }
        ]
      },
      {
        "artifactType": 30,
        "location": 3,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/dt-ti50.tar.bz2"
          }
        ]
      },
      {
        "artifactType": 30,
        "location": 3,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifacts_tmp_1/nt-ti50.tar.bz2"
          }
        ]
      }
    ]
  }
}'''

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
      'postsubmit',
      api.post_check(post_process.DoesNotRun, 'snoop: report_stage'),
  )

  yield test('cq', api.post_check(post_process.DoesNotRun,
                                  'snoop: report_stage'), cq=True,
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
      builder='firmware-zephyr-cq',
      input_properties={
          'firmware_location': common_pb2.PLATFORM_ZEPHYR,
          'bump_version': False,
          'set_suite_scheduling': True,
          'avb_enabled': True,
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
      api.step_data('sending pub/sub notifications.read fw metadata',
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
      api.step_data('sending pub/sub notifications.read fw metadata',
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
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          ZEPHYR_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data('sending pub/sub notifications.read fw metadata',
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
              'gs://firmware-image-archive/firmware-R126-15886.2.B/1234.56.0/brox/firmware_from_source.tar.bz2'
          ]),
      api.post_check(
          post_process.LogContains,
          'sending pub/sub notifications.publish artifacts to pubsub (8).build status pubsub update',
          'message', [
              'artifacts',
              'gs://firmware-image-archive/firmware-R126-15886.2.B/1234.56.0/rex/firmware_from_source.tar.bz2'
          ]),
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
          'sending pub/sub notifications.read fw metadata',
          api.file.read_proto(
              JsonToProto(
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

  sdk_pin_path = 'src/platform/ti50/sdk-version'
  yield test(
      'firmware-ti50-cq',
      api.step_data(
          'read chromiumos-sdk pin.read [CLEANUP]/chromiumos_workspace/{}'
          .format(sdk_pin_path), api.file.read_text('2022.01.20.073008\n')),
      api.post_check(post_process.DoesNotRun,
                     'configure builder.cros_infra_config.gitiles-fetch-ref'),
      cq=True, builder='firmware-ti50-cq', input_properties={
          'firmware_location': 3,
          'chromiumos_sdk_pin_file': sdk_pin_path,
      })

  yield test(
      'firmware-ti50-postsubmit',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          TI50_ARTIFACTS),
      api.path.files_exist(api.path.cleanup_dir /
                           'artifacts_tmp_1/firmware_metadata.jsonpb'),
      api.step_data(
          'sending pub/sub notifications.read fw metadata',
          api.file.read_proto(
              FirmwareArtifactInfo(objects=[
                  FirmwareArtifactInfo.ObjectInfo(
                      file_name='dt-ti50.tar.bz2',
                      tarball_info=FirmwareArtifactInfo.TarballInfo(
                          board=['betty'], publish_to_goldeneye=True,
                          type='GSC')),
              ]))), builder='firmware-ti50-postsubmit', input_properties={
                  'firmware_location': common_pb2.PLATFORM_TI50,
                  'chromiumos_sdk_pin_file': sdk_pin_path,
                  'set_suite_scheduling': True,
                  'signing_allowed_builder_names': [
                      'staging-firmware-ti50-postsubmit',
                      'firmware-ti50-postsubmit',
                  ],
                  'pao_signing_config': {
                      "project": "chromeos",
                      "keyring": "ring",
                      "key": "pao-key"
                  },
              })

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
      'create tast artifacts',
      api.step_data(
          'Create Ti50 Tast artifacts.gsutil list',
          stdout=api.raw_io.output_text(
              'gs://chromeos-image-archive/build0/ti50.tar.bz2')),
      builder='firmware-ti50-postsubmit', input_properties={
          '$chromeos/build_menu': {
              'container_version_format':
                  '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          'firmware_location':
              common_pb2.PLATFORM_TI50,
          'signing_allowed_builder_names': [
              'staging-firmware-ti50-postsubmit',
              'firmware-ti50-postsubmit',
          ],
      })

  yield test(
      'create tast artifacts missing tar files',
      api.step_data('Create Ti50 Tast artifacts.gsutil list', retcode=1),
      builder='firmware-ti50-postsubmit', input_properties={
          '$chromeos/build_menu': {
              'container_version_format':
                  '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          'firmware_location':
              common_pb2.PLATFORM_TI50,
          'signing_allowed_builder_names': [
              'staging-firmware-ti50-postsubmit',
              'firmware-ti50-postsubmit',
          ],
      })

  yield test(
      'create tast artifacts archive missing json and bin files',
      api.step_data(
          'Create Ti50 Tast artifacts.gsutil list',
          stdout=api.raw_io.output_text(
              'gs://chromeos-image-archive/build0/ti50.tar.bz2')),
      api.step_data('Create Ti50 Tast artifacts.Extract archive.untar',
                    retcode=2), builder='firmware-ti50-postsubmit',
      input_properties={
          '$chromeos/build_menu': {
              'container_version_format':
                  '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          'firmware_location':
              common_pb2.PLATFORM_TI50,
          'signing_allowed_builder_names': [
              'staging-firmware-ti50-postsubmit',
              'firmware-ti50-postsubmit',
          ],
      })
