# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan',
    'metadata',
    'skylab',
]

import functools

# Recipe engine imports
from recipe_engine import post_process

from google.protobuf import duration_pb2
from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  # Run with non-existent build target to trigger error path
  hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'my_first_little_hwtest'
  hw_test.run_via_cft = True
  unit_hw_test = api.skylab.UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  api.skylab.schedule_suites(
      [
          unit_hw_test,
      ],
      timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(
          target='non-existent-target',
      ),
  )


def GenTests(api):

  def StepSummaryEquals(check, step_odict, step, expected):
    """Check that the step's step_summary_text equals given value.

    Args:
      step (str) - The step to check the step_text of
      expected (str) - The expected value of the step_text

    Usage:
      yield TEST + \
          api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_summary_text == expected)

  require_step = functools.partial(api.post_check, post_process.MustRunRE)

  yield api.test(
      'no_build_target',
      api.properties(**{
          '$chromeos/skylab': SkylabProperties(
              enable_container_support=True,
          )
      }),
      require_step('.*configure test-builder'),
      api.post_check(
          StepSummaryEquals,
          'schedule skylab tests v2.create test requests.configure test-builder',
          "Execution via container requested, but no container metadata for build target 'another_target'",
      ),
  )
