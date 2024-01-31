# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests companions in test plans conversion into CTP request."""

from google.protobuf import duration_pb2

from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_plan',
    'metadata',
    'skylab',
]



def RunSteps(api):
  builder_name = 'target-cq'
  hw_test_unit = api.cros_test_plan.test_api.multi_dut_hw_test_unit
  hw_test_unit.common.builder_name = builder_name
  hw_test_unit.common.build_target.name = 'target'
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.companions[0].board = api.properties.get('companion_board', 'target')
  hw_test.companions[1].config.android.android_image_version \
                                     = api.properties.get('android_version', '')
  hw_test.common.display_name = 'my_first_little_hwtest'
  unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  with api.step.nest('schedule suites') as step:
    api.skylab.schedule_suites(
        [
            unit_hw_test,
        ], timeout=duration_pb2.Duration(seconds=3600),
        container_metadata=api.metadata.test_api.mock_metadata(target='target'))


def GenTests(api):
  yield api.test(
      'success',
      api.properties(companion_board='target'),
      api.post_process(
          post_process.LogContains,
          'schedule suites.schedule skylab tests v2.buildbucket.schedule',
          'request', [
              '"gmsCorePackage": "latest_stable"', 'secondaryDevices', 'pixel7',
              '"runViaTrv2": true'
          ]),
      # request should not contain empty values in the oneof list.
      api.post_process(
          post_process.LogDoesNotContain,
          'schedule suites.schedule skylab tests v2.buildbucket.schedule',
          'request', ['"androidImageVersion": ""', '"gmsCorePackage": ""']),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS')

  # normally unspecified, android version should be sent to CTP when specified.
  yield api.test(
      'success-with-android-version',
      api.properties(companion_board='target', android_version='12'),
      api.post_process(
          post_process.LogContains,
          'schedule suites.schedule skylab tests v2.buildbucket.schedule',
          'request',
          ['"gmsCorePackage": "latest_stable"', '"androidImageVersion": "12"']),
      api.post_process(post_process.DropExpectation), status='SUCCESS')

  yield api.test('companion-different-board',
                 api.properties(companion_board='anothertarget'),
                 api.post_check(post_process.StepFailure, 'schedule suites'),
                 api.post_process(post_process.DropExpectation),
                 status='FAILURE')
