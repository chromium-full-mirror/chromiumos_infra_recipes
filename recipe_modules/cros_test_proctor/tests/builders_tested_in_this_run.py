# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests setting the builder_tested_in_this_run property."""

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_proctor',
    'cros_test_plan',
]



def RunSteps(api):
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  _ = api.cros_test_proctor.schedule_tests(
      test_plan=test_plan, passed_tests=[],
      previously_failed_now_exonerable_hw_suites=[], previous_test_results={},
      timeout=api.cros_test_proctor.timeout)
  api.assertions.assertCountEqual(
      api.cros_test_proctor.builders_tested_in_this_run,
      api.properties['expected_tested_builders'])


def GenTests(api):

  yield api.test(
      'basic',
      api.properties(expected_tested_builders=['test-builder']),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'test-value-override',
      api.properties(
          expected_tested_builders=['builder-cq', 'another-builder-cq']),
      api.cros_test_proctor.builders_tested_in_this_run(
          ['builder-cq', 'another-builder-cq']),
      api.post_process(DropExpectation),
  )
