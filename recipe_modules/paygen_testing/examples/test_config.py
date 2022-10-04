# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from PB.chromiumos.common import DeltaType
from PB.chromiumos.common import ImageType
from PB.recipe_modules.chromeos.paygen_testing.examples.test import TestPaygenProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'paygen_testing',
    'cros_storage',
    'gitiles',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = TestPaygenProperties


def RunSteps(api, properties):
  test_artifact_root = api.cros_storage.ArtifactRoot('test-bucket',
                                                     'canary-channel',
                                                     properties.builder_name,
                                                     '13337.0.1')
  test_unsigned_image = (
      api.cros_storage.UnsignedImage(test_artifact_root,
                                     ImageType.Value('IMAGE_TYPE_RECOVERY'),
                                     'R82'))
  src_test_artifact_root = api.cros_storage.ArtifactRoot(
      'test-bucket', 'canary-channel', properties.builder_name, '13336.0.1')
  src_test_unsigned_image = (
      api.cros_storage.UnsignedImage(src_test_artifact_root,
                                     ImageType.Value('IMAGE_TYPE_RECOVERY'),
                                     'R82'))
  test_dlc_image = (
      api.cros_storage.DLCImage(test_artifact_root, 'termina-dlc', 'package',
                                'dlc.img'))

  api.cros_storage.DLCImage(src_test_artifact_root, 'termina-dlc', 'package',
                            'gvtgcmjugztghjioi4bbf32rlvybuioo')

  unsigned_full_payload = api.cros_storage.FullPayload(test_unsigned_image,
                                                       'abc123')
  unsigned_delta_payload = api.cros_storage.DeltaPayload(
      test_unsigned_image, src_test_unsigned_image, 'abc123')

  api.cros_storage.FullPayload(src_test_unsigned_image, 'abc123')
  delta_dlc_payload = api.cros_storage.DeltaDLCPayload(
      test_dlc_image, test_dlc_image, 'gvtgcmjugztghjioi4bbf32rlvybuioo')

  # Create delta and full test configs
  api.paygen_testing.create_paygen_test_config(
      tgt_payload=unsigned_delta_payload, delta_type=DeltaType.Value('OMAHA'),
      applicable_models=['woomax'])
  full_test_config = api.paygen_testing.create_paygen_test_config(
      tgt_payload=unsigned_full_payload, delta_type=DeltaType.Value('OMAHA'),
      src_version='13336.0.1', src_channel='canary-channel')

  if properties.expected_build_target_name:
    api.assertions.assertEqual(full_test_config.build_target_name,
                               properties.expected_build_target_name)

  if properties.expected_test_build_target:
    api.assertions.assertEqual(full_test_config.test_build_target,
                               properties.expected_test_build_target)

  # The source payload does not exist.
  with api.assertions.assertRaises(api.step.StepFailure):
    api.paygen_testing.create_paygen_test_config(
        tgt_payload=unsigned_delta_payload, delta_type=DeltaType.Value('OMAHA'))
  # Full payload without source information.
  with api.assertions.assertRaises(api.step.StepFailure):
    api.paygen_testing.create_paygen_test_config(
        tgt_payload=unsigned_full_payload, delta_type=DeltaType.Value('OMAHA'))
  # Unsupported Payload type.
  with api.assertions.assertRaises(api.step.StepFailure):
    api.paygen_testing.create_paygen_test_config(
        tgt_payload=delta_dlc_payload, delta_type=DeltaType.Value('OMAHA'))

  api.assertions.assertEqual(
      full_test_config.get_test_runner_tags()['label-pool'],
      properties.expected_quota_scheduler_label_pool or 'quota')
  api.assertions.assertEqual(
      full_test_config.get_test_runner_tags()['quota_account'],
      properties.expected_quota_scheduler_account or 'legacypool-bvt')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(builder_name='zork', expected_test_build_target='zork'),
      api.gitiles.get_file(
          api.paygen_testing.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.cros_storage.test_listing(
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
      api.cros_storage.test_listing(
          'discover gs artifacts (2).gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
  )
  yield api.test(
      'test-quota-scheduler-config',
      api.properties(
          builder_name='zork', expected_test_build_target='zork',
          expected_quota_scheduler_account='foo',
          expected_quota_scheduler_label_pool='bar', **{
              '$chromeos/paygen_testing': {
                  'quota_scheduler_config': {
                      'account': 'foo',
                      'label_pool': 'bar',
                  },
              },
          }),
      api.gitiles.get_file(
          api.paygen_testing.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.cros_storage.test_listing(
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
      api.cros_storage.test_listing(
          'discover gs artifacts (2).gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
  )

  generate_test_config_output = """{
    "perTargetTestRequirements": [
        {
            "targetCriteria": {
                "buildTarget": "zork",
                "builderName": "zork-release-main"
            },
            "hwTestCfg": {
                "hwTest": [
                    {
                        "common": {
                            "displayName": "zork-release-main.hw.bvt-tast-cq",
                            "critical": false,
                            "testSuiteGroups": [
                                {
                                    "testSuiteGroup": "default-tast-suites"
                                }
                            ]
                        },
                        "suite": "bvt-tast-cq",
                        "skylabBoard": "zork",
                        "hwTestSuiteType": "TAST",
                        "pool": "DUT_POOL_QUOTA"
                    }
                ]
            }
        }
    ]
}"""

  yield api.test(
      'generate',
      api.properties(
          builder_name='zork', expected_test_build_target='zork',
          expected_build_target_name='zork', **{
              '$chromeos/cros_test_plan': {
                  'generate_target_test_requirements_from_source': True,
              },
          }),
      api.gitiles.get_file(
          api.paygen_testing.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.step_data('generate target test requirements.generate_test_config',
                    stdout=api.raw_io.output(generate_test_config_output)),
      api.step_data(
          'generate target test requirements (2).generate_test_config',
          stdout=api.raw_io.output(generate_test_config_output)),
      api.cros_storage.test_listing(
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
      api.cros_storage.test_listing(
          'discover gs artifacts (2).gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'generate target test requirements.generate_test_config',
          ['./board_config/generate_test_config', 'zork-release-main']),
  )

  yield api.test(
      'variant',
      api.properties(builder_name='atlas-kernelnext',
                     expected_test_build_target='atlas',
                     expected_build_target_name='atlas-kernelnext'),
      api.gitiles.get_file(
          api.paygen_testing.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.cros_storage.test_listing(
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
      api.cros_storage.test_listing(
          'discover gs artifacts (2).gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
  )
