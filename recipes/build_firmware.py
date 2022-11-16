# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds and tests firmware.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
This recipe should only be used for ToT firmware builds.
"""

from google.protobuf.json_format import MessageToDict

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.firmware import BuildAllFirmwareRequest
from PB.chromite.api.firmware import TestAllFirmwareRequest
import PB.chromiumos.common as common_pb2
from PB.recipes.chromeos.build_firmware import BuildFirmwareProperties

DEPS = [
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/properties',
    "recipe_engine/resultdb",
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
    'failures',
    'src_state',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildFirmwareProperties


def UploadTestResults(api, location, builder_name):
  if location == common_pb2.PLATFORM_ZEPHYR:
    cros_src_path = api.cros_source.workspace_path
    test_results = cros_src_path.join(
        'src/platform/ec/twister-out-llvm/twister.json')

    with api.step.nest('Upload EC Firmware test results') as pres:
      try:
        rdb_cmd = [
            'vpython3',
            cros_src_path.join('src/platform/ec/util/zephyr_to_resultdb.py'),
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
    api.bcid_reporter.report_stage('start')
  if properties.manifest_branch:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto
    commit.ref = 'refs/heads/{}'.format(properties.manifest_branch)
  else:
    commit = None
  with api.build_menu.configure_builder(commit=commit) \
     as config, api.build_menu.setup_workspace():
    chromiumos_sdk_version = _read_chromiumos_sdk_pin(api, properties)
    api.build_menu.setup_chroot(sdk_version=chromiumos_sdk_version)

    service = api.cros_build_api.FirmwareService
    chroot = api.cros_sdk.chroot
    location = properties.firmware_location or config.general.firmware_location

    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('compile')
    response = service.BuildAllFirmware(
        BuildAllFirmwareRequest(firmware_location=location, chroot=chroot,
                                code_coverage=properties.code_coverage),
        name='build firmware')
    binary_sizes = {}
    if response.metrics and response.metrics.value:
      for fw_metric in response.metrics.value:
        region_prefix = ""
        if fw_metric.platform_name:
          region_prefix += fw_metric.platform_name + "_"
        if fw_metric.target_name:
          region_prefix += fw_metric.target_name + "_"
        for fw_section in fw_metric.fw_section:
          if fw_section.track_on_gerrit:
            if fw_section.used:
              binary_sizes[region_prefix + fw_section.region] = fw_section.used
            if fw_section.total:
              binary_sizes[region_prefix + fw_section.region +
                           ".budget"] = fw_section.total

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

    uploaded_artifacts = api.build_menu.upload_artifacts(
        config=config, report_to_spike=True)

    with api.failures.ignore_exceptions():
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
        for artifact_name in uploaded_artifacts[2]['FIRMWARE_TARBALL']:
          archive = "gs://%s/%s/%s" % (uploaded_artifacts[0],
                                       uploaded_artifacts[1], artifact_name)
          sign_image_props["archive"] = archive
          requests.append(
              api.buildbucket.schedule_request(bucket=bucket, builder=builder,
                                               properties=sign_image_props))

        api.buildbucket.schedule(requests)

    UploadTestResults(api, location, build.builder.builder)

    CreateContainers(api, config)


def _read_chromiumos_sdk_pin(api, properties):
  if properties.chromiumos_sdk_pin_file:
    with api.step.nest('read chromiumos-sdk pin'):
      filepath = api.src_state.workspace_path.join(
          properties.chromiumos_sdk_pin_file)
      return api.file.read_text('read {}'.format(filepath), filepath).strip()
  return None


def _invoke_signing_for_current_build(builder_name, uploaded_artifacts,
                                      properties):
  '''
  Whether signing for current build should be invoked.

  Args:
    builder_name (str): Current builder name.
    uploaded_artifacts (UploadedArtifacts): Uploaded artifacts.
    properties (BuildFirmwareProperties): Build firmware properties for current build.

  Returns:
    (bool): True if signing should be invoked. False otherwise.
  '''
  valid_builder = builder_name in properties.signing_allowed_builder_names and properties.sign_image_properties
  artifact_upload_succeeded = uploaded_artifacts and len(uploaded_artifacts) > 2
  return valid_builder and artifact_upload_succeeded


def GenTests(api):

  def get_signing_image_props_for_test(is_staging=False):
    '''
    Get SignImageProperties for test.

    Args:
      is_staging (bool): Whether properties need for staging.

    Returns:
      (dict): SignImageProperties object as dict for testing.
    '''
    return {
        "image_type": 13,
        "channel": 0,
        "keyset": "test-keyset",
        "signer_type": 2 if is_staging else 1,
        "allow_non_release_signer_bucket": True,
        "gsc_instructions": {
            "target": 1,
        },
    }

  def test(name, *args, **kwargs):
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('input_properties', dict(firmware_location=1))
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, *args)

  yield test('postsubmit',)

  yield test('cq', cq=True, builder='fw-ec-cq')

  yield test(
      'zephyr-cq', cq=True, builder='fw-ec-cq',
      input_properties=(dict(firmware_location=common_pb2.PLATFORM_ZEPHYR)))

  sdk_pin_path = 'src/platform/ti50/sdk-version'
  yield test(
      'firmware-ti50-cq',
      api.step_data(
          'read chromiumos-sdk pin.read [CLEANUP]/chromiumos_workspace/{}'
          .format(sdk_pin_path), api.file.read_text('2022.01.20.073008\n')),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DoesNotRun,
                     'configure builder.cros_infra_config.gitiles-fetch-ref'),
      cq=True, builder='firmware-ti50-cq', input_properties=dict(
          firmware_location=3,
          chromiumos_sdk_pin_file=sdk_pin_path,
      ))

  yield test(
      'upload-fail',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1), api.post_check(post_process.StatusAnyFailure))

  yield test(
      'working-upload-fail',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          retcode=1), api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun, 'schedule signing build'),
      input_properties=(dict(firmware_location=1)))

  yield test(
      'fw-test-fail',
      api.step_data('test firmware.call build API script', retcode=1),
      api.post_check(post_process.MustRun, 'Upload EC Firmware test results'),
      api.post_check(post_process.StatusAnyFailure),
      input_properties=(dict(firmware_location=common_pb2.PLATFORM_ZEPHYR)))

  yield test(
      'upload-test-results-fail',
      api.step_data('Upload EC Firmware test results.run', retcode=1),
      api.post_check(
          post_process.StepTextContains,
          'Upload EC Firmware test results',
          ['Failed to upload test results'],
      ),
      api.post_check(post_process.StepFailure,
                     'Upload EC Firmware test results.run'),
      api.post_check(post_process.StatusSuccess),
      input_properties=(dict(firmware_location=common_pb2.PLATFORM_ZEPHYR)))

  yield test(
      'signing-invocation', api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'schedule signing build'),
      builder='fw-ec-postsubmit', input_properties=(dict(
          firmware_location=1,
          signing_allowed_builder_names=['fw-ec-postsubmit'],
          sign_image_properties=get_signing_image_props_for_test(),
      )))

  yield test(
      'staging-signing-invocation', api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'schedule signing build'),
      builder='fw-ec-postsubmit', bucket='staging', input_properties=(dict(
          firmware_location=1,
          signing_allowed_builder_names=['fw-ec-postsubmit'],
          sign_image_properties=get_signing_image_props_for_test(
              is_staging=True),
      )))

  yield test('output-binary-sizes', api.post_check(post_process.StatusSuccess),
             api.post_check(post_process.MustRun, 'output binary sizes'),
             api.post_check(post_process.MustRun, 'output got_revision'))

  yield test(
      'branched-manifest', api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'configure builder.cros_infra_config.gitiles-fetch-ref'),
      api.post_process(
          post_process.StepCommandContains,
          'ensure synced checkout.repo init',
          [
              '--manifest-branch',
              'factory-firmware-ti50-B',
          ],
      ), builder='firmware-ti50-cq',
      input_properties=dict(firmware_location=3,
                            chromiumos_sdk_pin_file=sdk_pin_path,
                            manifest_branch="factory-firmware-ti50-B"))

  yield test(
      'create test containers', api.post_check(post_process.StatusSuccess),
      api.post_check(
          post_process.MustRun,
          'Create test containers.create test service containers.upload container metadata.gsutil upload'
      ), builder='amd64-generic-postsubmit', input_properties=dict(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'amd64-generic-postsubmit',
                  },
                  'container_version_format':
                      "{staging?}{build-target}-postsubmit.{cros-version}-{bbid}",
              },
              '$chromeos/cros_relevance': {
                  'force_postsubmit_relevance': True
              }
          }))

  yield test(
      'create test containers exception',
      api.post_check(post_process.StatusSuccess),
      api.step_data('Create test containers.set target_versions', retcode=1),
      api.post_check(
          post_process.DoesNotRun,
          'Create test containers.create test service containers.upload container metadata.gsutil upload'
      ),
      api.post_check(post_process.StepTextContains, 'Create test containers',
                     ['Failed to create containers']),
      builder='amd64-generic-postsubmit', input_properties=dict(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'amd64-generic-postsubmit',
                  },
                  'container_version_format':
                      "{staging?}{build-target}-postsubmit.{cros-version}-{bbid}",
              },
              '$chromeos/cros_relevance': {
                  'force_postsubmit_relevance': True
              }
          }))
