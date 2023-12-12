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

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  builder_name = 'target-cq'
  hw_test_unit = api.cros_test_plan.test_api.multi_dut_no_android_hw_test_unit
  hw_test_unit.common.builder_name = builder_name
  hw_test_unit.common.build_target.name = 'target'
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.companions[0].board = api.properties.get('companion_board', 'target')
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
      'success-not-use-trv2',
      api.properties(companion_board='target', exclude_android=True),
      api.post_process(
          post_process.LogDoesNotContain,
          'schedule suites.schedule skylab tests v2.buildbucket.schedule',
          'request', ['"runViaTrv2": true']),
      api.post_process(post_process.DropExpectation), status='SUCCESS')
