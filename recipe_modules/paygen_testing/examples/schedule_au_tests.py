# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from google.protobuf import duration_pb2

from PB.chromiumos.common import DeltaType
from PB.recipe_modules.chromeos.paygen_testing.paygen_testing import PaygenTestingProperties
from PB.recipe_modules.chromeos.paygen_testing.paygen_testing import TestRequestOpts
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'paygen_testing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  build_target_name = 'octopus-kernelnext'
  test_build_target = 'octopus'
  tgt_channel = 'canary-channel'
  tgt_version = '13415.0.0'
  tgt_payload_uri = (
      'gs://chromeos-releases/canary-channel/octopus/13415.0.0/payloads/'
      'chromeos_13414.0.0-13415.0.0_octopus_canary-channel_delta_test.bin-abc')
  tgt_archive_uri = 'gs://chromeos-image-archive/octopus-release/R86-13415.0.0'
  delta_type_omaha = DeltaType.Value('OMAHA')
  applicable_models = ['ampton', 'bloog']

  src_version_13414 = '13414.0.0'
  src_payload_uri_13414 = (
      'gs://chromeos-releases/canary-channel/octopus/13414.0.0/payloads/'
      'chromeos_13414.0.0_octopus_canary-channel_full_test.bin-def')
  src_artifact_uri_13414 = ('gs://chromeos-releases/canary-channel/octopus/'
                            '13414.0.0')
  tgt_container_metadata_uri = 'gs://chromeos-releases/canary-channel/octopus/13414.0.0/metadata/containers.jsonpb'
  paygen_test_config_13414 = api.paygen_testing.PaygenTestConfig(
      test_build_target=test_build_target, build_target_name=build_target_name,
      tgt_channel=tgt_channel, tgt_payload_uri=tgt_payload_uri,
      tgt_archive_uri=tgt_archive_uri,
      tgt_container_metadata_uri=tgt_container_metadata_uri,
      tgt_version=tgt_version, src_payload_uri=src_payload_uri_13414,
      src_artifact_uri=src_artifact_uri_13414, src_version=src_version_13414,
      is_delta_update=True, delta_type=delta_type_omaha,
      applicable_models=applicable_models)
  paygen_test_config_13414_no_models = api.paygen_testing.PaygenTestConfig(
      test_build_target=test_build_target, build_target_name=build_target_name,
      tgt_channel=tgt_channel, tgt_payload_uri=tgt_payload_uri,
      tgt_archive_uri=tgt_archive_uri,
      tgt_container_metadata_uri=tgt_container_metadata_uri,
      tgt_version=tgt_version, src_payload_uri=src_payload_uri_13414,
      src_artifact_uri=src_artifact_uri_13414, src_version=src_version_13414,
      is_delta_update=True, delta_type=delta_type_omaha, applicable_models=[])

  src_version_13413 = '13413.0.0'
  src_payload_uri_13413 = (
      'gs://chromeos-releases/canary-channel/octopus/13413.0.0/payloads/'
      'chromeos_13413.0.0_octopus_canary-channel_full_test.bin-def')
  src_artifact_uri_13413 = ('gs://chromeos-releases/canary-channel/octopus/'
                            '13413.0.0')
  paygen_test_config_13413 = api.paygen_testing.PaygenTestConfig(
      test_build_target=test_build_target, build_target_name=build_target_name,
      tgt_channel=tgt_channel, tgt_payload_uri=tgt_payload_uri,
      tgt_archive_uri=tgt_archive_uri,
      tgt_container_metadata_uri=tgt_container_metadata_uri,
      tgt_version=tgt_version, src_payload_uri=src_payload_uri_13413,
      src_artifact_uri=src_artifact_uri_13413, src_version=src_version_13413,
      is_delta_update=True, delta_type=delta_type_omaha,
      applicable_models=applicable_models)

  # Ordinary scheduling for one or multiple paygen test configs.
  # There doesn't seem to be a way to inspect the scheduled build's input props.
  api.paygen_testing.schedule_au_tests([paygen_test_config_13414])
  api.paygen_testing.schedule_au_tests(
      [paygen_test_config_13414, paygen_test_config_13413])

  api.assertions.assertIsNone(api.paygen_testing.schedule_au_tests([]))
  api.assertions.assertIsNotNone(
      api.paygen_testing.schedule_au_tests([paygen_test_config_13414_no_models
                                           ]))
  api.assertions.assertIsNotNone(
      api.paygen_testing.schedule_au_tests([paygen_test_config_13414]))
  paygen_test_config_13414._applicable_models = None
  api.assertions.assertIsNotNone(
      api.paygen_testing.schedule_au_tests([paygen_test_config_13414]))
  paygen_test_config_13414._applicable_models = applicable_models

  # Test test config merging by model.
  _, requests = api.paygen_testing.create_au_test_tagged_requests(
      [paygen_test_config_13414, paygen_test_config_13414_no_models])
  api.assertions.assertEqual(
      3,  # 3 because two models and one for no specific model.
      len(requests.keys()))
  _, requests = api.paygen_testing.create_au_test_tagged_requests(
      [paygen_test_config_13414, paygen_test_config_13413])
  api.assertions.assertEqual(
      2,  # 2 because two models (and test configs should be merged).
      len(requests.keys()))


def GenTests(api):
  yield api.test('basic', api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))

  yield api.test(
      'with-request-overrides',
      api.properties(
          **{
              '$chromeos/paygen_testing':
                  PaygenTestingProperties(
                      test_request_opts=TestRequestOpts(
                          max_retries=1, timeout=duration_pb2.Duration(
                              seconds=100)))
          }), api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  # TODO(b/243580346): While I work on untangling the code here, we have these
  # mock methods being used in paygen.py but not triggering coverage. Call them
  # here so coverage is satisfied.
  _ = api.paygen_testing.EXAMPLE_GEN_REQUEST_DELTA_DLC
  _ = api.paygen_testing.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED
  _ = api.paygen_testing.EXAMPLE_GEN_REQUEST_FULL_DLC
  _ = api.paygen_testing.EXAMPLE_GEN_REQUESTS_DELTA_N2N
