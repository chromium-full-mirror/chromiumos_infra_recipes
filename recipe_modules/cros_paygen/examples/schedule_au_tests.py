# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from google.protobuf import duration_pb2
from PB.recipe_modules.chromeos.cros_paygen.cros_paygen import CrosPaygenProperties
from PB.recipe_modules.chromeos.cros_paygen.cros_paygen import TestRequestOpts
from PB.chromiumos.common import DeltaType

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_paygen',
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
  paygen_test_config_13414 = api.cros_paygen.PaygenTestConfig(
      test_build_target=test_build_target, build_target_name=build_target_name,
      tgt_channel=tgt_channel, tgt_payload_uri=tgt_payload_uri,
      tgt_archive_uri=tgt_archive_uri,
      tgt_container_metadata_uri=tgt_container_metadata_uri,
      tgt_version=tgt_version, src_payload_uri=src_payload_uri_13414,
      src_artifact_uri=src_artifact_uri_13414, src_version=src_version_13414,
      is_delta_update=True, delta_type=delta_type_omaha,
      applicable_models=applicable_models)
  paygen_test_config_13414_no_models = api.cros_paygen.PaygenTestConfig(
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
  paygen_test_config_13413 = api.cros_paygen.PaygenTestConfig(
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
  api.cros_paygen.schedule_au_tests([paygen_test_config_13414])
  api.cros_paygen.schedule_au_tests(
      [paygen_test_config_13414, paygen_test_config_13413])

  api.assertions.assertIsNone(api.cros_paygen.schedule_au_tests([]))
  api.assertions.assertIsNotNone(
      api.cros_paygen.schedule_au_tests([paygen_test_config_13414_no_models]))
  api.assertions.assertIsNotNone(
      api.cros_paygen.schedule_au_tests([paygen_test_config_13414]))
  paygen_test_config_13414._applicable_models = None
  api.assertions.assertIsNotNone(
      api.cros_paygen.schedule_au_tests([paygen_test_config_13414]))
  paygen_test_config_13414._applicable_models = applicable_models


def GenTests(api):
  yield api.test('basic', api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))

  yield api.test(
      'with-request-overrides',
      api.properties(
          **{
              '$chromeos/cros_paygen':
                  CrosPaygenProperties(
                      test_request_opts=TestRequestOpts(
                          max_retries=1, timeout=duration_pb2.Duration(
                              seconds=100)))
          }), api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
