# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from google.protobuf import duration_pb2
from PB.recipe_modules.chromeos.cros_paygen.cros_paygen import CrosPaygenProperties
from PB.recipe_modules.chromeos.cros_paygen.cros_paygen import TestRequestOpts
from PB.chromiumos.common import DeltaType

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_paygen',
]


def RunSteps(api):
  build_target_name = 'octopus'
  tgt_channel = 'canary-channel'
  tgt_version = '13415.0.0'
  tgt_payload_uri = (
      'gs://chromeos-releases/canary-channel/octopus/13415.0.0/payloads/'
      'chromeos_13414.0.0-13415.0.0_octopus_canary-channel_delta_test.bin-abc')
  tgt_archive_uri = 'gs://chromeos-image-archive/octopus-release/R86-13415.0.0'
  src_version = '13414.0.0'
  src_payload_uri = (
      'gs://chromeos-releases/canary-channel/octopus/13414.0.0/payloads/'
      'chromeos_13414.0.0_octopus_canary-channel_full_test.bin-def')
  src_artifact_uri = 'gs://chromeos-releases/canary-channel/octopus/13414.0.0'
  delta_type = DeltaType.Value('OMAHA')
  applicable_models = ['ampton']
  paygen_test_config = api.cros_paygen.PaygenTestConfig(
      build_target_name=build_target_name, tgt_channel=tgt_channel,
      tgt_payload_uri=tgt_payload_uri, tgt_archive_uri=tgt_archive_uri,
      tgt_version=tgt_version, src_payload_uri=src_payload_uri,
      src_artifact_uri=src_artifact_uri, src_version=src_version,
      is_delta_update=True, delta_type=delta_type,
      applicable_models=applicable_models)
  # No testable models.
  api.assertions.assertIsNone(
      api.cros_paygen.schedule_au_tests([paygen_test_config], ['not-a-model']))
  api.assertions.assertIsNotNone(
      api.cros_paygen.schedule_au_tests([paygen_test_config]))
  paygen_test_config._applicable_models = None
  api.assertions.assertIsNotNone(
      api.cros_paygen.schedule_au_tests([paygen_test_config]))


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'with-request-overrides',
      api.properties(
          **{
              '$chromeos/cros_paygen':
                  CrosPaygenProperties(
                      test_request_opts=TestRequestOpts(
                          max_retries=1, timeout=duration_pb2.Duration(
                              seconds=100)))
          }))
