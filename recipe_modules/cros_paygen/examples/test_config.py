# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_paygen',
    'cros_storage',
    'gitiles',
]

from recipe_engine import post_process
from PB.chromiumos.common import DeltaType, ImageType
from PB.recipe_modules.chromeos.cros_paygen.examples.test import TestPaygenProperties

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

  # Valid Payload types.
  delta_test_config = api.cros_paygen.create_paygen_test_config(
      tgt_payload=unsigned_delta_payload, delta_type=DeltaType.Value('OMAHA'),
      applicable_models=['woomax'])
  full_test_config = api.cros_paygen.create_paygen_test_config(
      tgt_payload=unsigned_full_payload, delta_type=DeltaType.Value('OMAHA'),
      src_version='13336.0.1', src_channel='canary-channel')

  if properties.expected_test_build_target:
    api.assertions.assertEqual(full_test_config.build_target_name,
                               properties.expected_test_build_target)

  # The source payload does not exist.
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_paygen.create_paygen_test_config(
        tgt_payload=unsigned_delta_payload, delta_type=DeltaType.Value('OMAHA'))
  # Full payload without source information.
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_paygen.create_paygen_test_config(
        tgt_payload=unsigned_full_payload, delta_type=DeltaType.Value('OMAHA'))
  # Unsupported Payload type.
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_paygen.create_paygen_test_config(
        tgt_payload=delta_dlc_payload, delta_type=DeltaType.Value('OMAHA'))

  # Test get_testable_models.
  # Models is None, self._applicable_models is non-empty.
  api.assertions.assertCountEqual(delta_test_config._get_testable_models(),
                                  ['woomax'])
  # Models and self._applicable_models is non-empty.
  api.assertions.assertCountEqual(
      delta_test_config._get_testable_models(['woomax', 'other']), ['woomax'])
  # Models is non-empty, self._applicable_models is None.
  api.assertions.assertCountEqual(
      full_test_config._get_testable_models(['woomax', 'other']),
      ['woomax', 'other'])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(builder_name='zork', expected_test_build_target='zork'),
      api.gitiles.get_file(api.cros_paygen.TEST_TARGET_TEST_REQUIREMENTS_DATA),
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
          builder_name='zork', expected_test_build_target='zork', **{
              '$chromeos/cros_test_plan': {
                  'generate_target_test_requirements_from_source': True,
              },
          }),
      api.gitiles.get_file(api.cros_paygen.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.step_data('generate target test requirements.generate_test_config',
                    stdout=api.raw_io.output_text(generate_test_config_output)),
      api.step_data(
          'generate target test requirements (2).generate_test_config',
          stdout=api.raw_io.output_text(generate_test_config_output)),
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
                     expected_test_build_target='atlas'),
      api.gitiles.get_file(api.cros_paygen.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.cros_storage.test_listing(
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
      api.cros_storage.test_listing(
          'discover gs artifacts (2).gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.11.0/payloads/chromeos_13505.11.0_coral_beta-channel_full_test.bin-gvtdqntcmnrtbspt25izgbw4ihykaibv'
      ),
  )
