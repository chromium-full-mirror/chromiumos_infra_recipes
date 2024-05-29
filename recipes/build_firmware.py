# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds and tests firmware.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
This recipe should only be used for ToT firmware builds and build_legacy_fw
(which is not deprecated) should be used for branch firmware builds.
"""

import collections
import re
import os

from google.protobuf.json_format import MessageToDict

import PB.chromiumos.common as common_pb2
from PB.chromite.api.firmware import BuildAllFirmwareRequest
from PB.chromite.api.firmware import TestAllFirmwareRequest
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'build_menu',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
    'failures',
    'src_state',
    'test_util',
]


PROPERTIES = BuildFirmwareProperties

# Artifacts that don't need to be signed.
SKIP_SIGNING_RE = re.compile(r'^(host_emulation|opentitan)-')


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
  with api.failures.ignore_exceptions():
    with api.step.nest('checking attestation eligibility') as pres:
      # Config determines whether to report artifacts.
      if api.cros_infra_config.config.artifacts.attestation_eligible:
        api.bcid_reporter.report_stage('start')
        pres.step_text = f'{api.cros_infra_config.config.id.name} is attestation eligible'
      else:
        pres.step_text = f'{api.cros_infra_config.config.id.name} NOT attestation eligible'
  with api.build_menu.configure_builder() \
     as config, api.build_menu.setup_workspace():
    chromiumos_sdk_version = _read_chromiumos_sdk_pin(api, properties)
    api.build_menu.setup_chroot(sdk_version=chromiumos_sdk_version)

    service = api.cros_build_api.FirmwareService
    chroot = api.cros_sdk.chroot
    location = properties.firmware_location or config.general.firmware_location

    with api.failures.ignore_exceptions():
      if api.cros_infra_config.config.artifacts.attestation_eligible:
        api.bcid_reporter.report_stage('compile')
    response = service.BuildAllFirmware(
        BuildAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                code_coverage=properties.code_coverage),
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
              binary_sizes[region_prefix + fw_section.region] = fw_section.used
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
                                 code_coverage=properties.code_coverage),
          name='test firmware')
    except StepFailure as ex:
      UploadTestResults(api, location, build.builder.builder)
      raise ex

    uploaded_artifacts, _ = api.build_menu.upload_artifacts(
        config=config, report_to_spike=api.cros_infra_config.config.artifacts
        .attestation_eligible)

    with api.failures.ignore_exceptions():
      if api.cros_infra_config.config.artifacts.attestation_eligible:
        api.bcid_reporter.report_stage('upload-complete')

    # Invoke signing if applies.
    if _invoke_signing_for_current_build(build.builder.builder,
                                         uploaded_artifacts, properties):
      with api.step.nest('schedule signing build'):
        requests = []
        sign_image_props = MessageToDict(properties.sign_image_properties,
                                         preserving_proto_field_name=True)
        bucket = 'staging' if api.build_menu.is_staging else 'release'
        builder = 'staging-sign-image' if api.build_menu.is_staging else 'sign-image'
        for artifact_name in [
            a for a in uploaded_artifacts.files_by_artifact['FIRMWARE_TARBALL']
            if not SKIP_SIGNING_RE.match(a)
        ]:
          archive = 'gs://%s/%s/%s' % (uploaded_artifacts.gs_bucket,
                                       uploaded_artifacts.gs_path,
                                       artifact_name)
          sign_image_props['archive'] = archive
          requests.append(
              api.buildbucket.schedule_request(bucket=bucket, builder=builder,
                                               properties=sign_image_props))

        api.buildbucket.schedule(requests)

    UploadTestResults(api, location, build.builder.builder)

    CreateContainers(api, config)

    CreateTi50TastArtifacts(api, location, config)


def CreateTi50TastArtifacts(api, location, config):
  """Create directories and files of artifacts needed by Ti50 Tast tests."""
  if location != common_pb2.PLATFORM_TI50:
    return
  with api.step.nest('Create Ti50 Tast artifacts'):

    artifacts_gs_bucket = config.artifacts.artifacts_gs_bucket
    signed_artifacts_gs_bucket = _to_signed_gs_bucket(artifacts_gs_bucket)
    artifacts_gs_path = _artifacts_gs_path(api, config)

    tars = _find_files_with_suffix(api, artifacts_gs_bucket, artifacts_gs_path,
                                   '.tar.bz2')
    if len(tars) == 0:
      return

    # CTP builder is not able to access releases bucket, therefore the
    # signed .bin files are copied back to the chromeos-image-archive bucket.
    bins = _find_files_with_suffix(api, signed_artifacts_gs_bucket,
                                   artifacts_gs_path, '.bin')

    temp_dir = api.path.mkdtemp()
    tast_dir = api.path.join(temp_dir, 'tast')
    tast_dir_empty = True
    download_dir = api.path.join(temp_dir, 'download')
    api.file.ensure_directory('Create download directory', download_dir)
    signing_re = re.compile(r'.*/ti50_Unknown_(.*).bin')
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
      for bin_file in bins:
        if bin_file.find(base) >= 0:
          dest_path = tast_subdir
          signing_info = signing_re.match(bin_file)
          if signing_info:
            dest_path = os.path.join(tast_subdir,
                                     'image_' + signing_info[1] + '.bin')
          api.gsutil.download(signed_artifacts_gs_bucket, bin_file, dest_path,
                              name='download signed image')
          tast_dir_empty = False
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


def _to_signed_gs_bucket(gs_bucket):
  """Convert a gs bucket to the corresponding signed bucket."""
  gs_bucket = gs_bucket.replace('staging-chromeos-image-archive',
                                'chromeos-releases-test')
  return gs_bucket.replace('chromeos-image-archive', 'chromeos-releases')


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
    status = kwargs.pop('status', 'SUCCESS')
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('input_properties', {'firmware_location': 1})
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, *args, status=status)

  yield test(
      'postsubmit',
      api.post_check(post_process.DoesNotRun, 'snoop: report_stage'),
  )

  yield test('cq', api.post_check(post_process.DoesNotRun,
                                  'snoop: report_stage'), cq=True,
             builder='fw-ec-cq')

  yield test('zephyr-cq', cq=True, builder='fw-ec-cq',
             input_properties={'firmware_location': common_pb2.PLATFORM_ZEPHYR})

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
      api.post_process(post_process.DropExpectation),
      builder='firmware-ti50-postsubmit', input_properties={
          'firmware_location': 3,
          'chromiumos_sdk_pin_file': sdk_pin_path,
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
      api.post_check(post_process.DoesNotRun, 'schedule signing build'),
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
      'signing-invocation',
      api.post_check(post_process.MustRun, 'schedule signing build'),
      builder='fw-ec-postsubmit', input_properties={
          'firmware_location': 1,
          'signing_allowed_builder_names': ['fw-ec-postsubmit'],
          'sign_image_properties': get_signing_image_props_for_test(),
      })

  yield test(
      'staging-signing-invocation',
      api.post_check(post_process.MustRun, 'schedule signing build'),
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
      api.step_data(
          'Create Ti50 Tast artifacts.gsutil list (2)',
          stdout=api.raw_io.output_text(
              'gs://chromeos-releases/build0/ti50.tar.bz2/ti50_Unknown_image.bin'
          )), builder='amd64-generic-snapshot', input_properties={
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'amd64-generic',
                  },
                  'container_version_format':
                      '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
              },
              '$chromeos/cros_relevance': {
                  'force_postsubmit_relevance': True
              },
              'firmware_location': common_pb2.PLATFORM_TI50
          })

  yield test(
      'create tast artifacts missing tar files',
      api.step_data('Create Ti50 Tast artifacts.gsutil list', retcode=1),
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
          },
          'firmware_location': common_pb2.PLATFORM_TI50
      })

  yield test(
      'create tast artifacts archive missing json and bin files',
      api.step_data(
          'Create Ti50 Tast artifacts.gsutil list',
          stdout=api.raw_io.output_text(
              'gs://chromeos-image-archive/build0/ti50.tar.bz2')),
      api.step_data(
          'Create Ti50 Tast artifacts.gsutil list (2)',
          stdout=api.raw_io.output_text(
              'gs://chromeos-releases/build0/ti50.tar.bz2/ti50_Unknown_image.bin'
          )),
      api.step_data('Create Ti50 Tast artifacts.Extract archive.untar',
                    retcode=2), builder='amd64-generic-snapshot',
      input_properties={
          '$chromeos/build_menu': {
              'build_target': {
                  'name': 'amd64-generic',
              },
              'container_version_format':
                  '{staging?}{build-target}-snapshot.{cros-version}-{bbid}',
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          'firmware_location': common_pb2.PLATFORM_TI50
      })
