# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to schedules child builders, watches for failures and triggers tests.

All builders run against the same source tree.

NOTE: This recipe will be merged with the main orchestrator recipe shortly.
"""

DEPS = [
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build',
    'test_manager',
    'test_plan',
]


def RunSteps(api):
  build_config = api.properties['build_config']
  builder = api.properties['builder']

  scheduled_builds = api.cros_build.schedule_child_builders(
      'schedule child builders', builder, build_config)

  # Defer exceptions until the end, so that we recover gracefully
  # from intermediate failures.
  with api.step.defer_results():
    builds = api.cros_build.collect(scheduled_builds).get_result()
    test_results = api.test_manager.run_tests(builds, step_name='test')

    # Verification steps raise exceptions for failures.
    # Since we're in a deferred context, the recipe will happily continue,
    # and will notify the CI when it's done.
    api.cros_build.verify_builds(builds)
    api.test_manager.verify_tests(test_results.get_result())


def GenTests(api):
  build_config = [
      dict(build_target='build_target1',),
      dict(build_target='build_target2',),
  ]

  builds = [
      api.cros_build.example('child_builder1', build_config[0]),
      api.cros_build.example('child_builder2', build_config[1]),
  ]

  properties = api.properties(builder='builder', build_config=build_config)

  yield (
      api.test('basic') + api.cros_build.simulated_collect_output(
          builds, step_name='test.collect') + properties +
      api.test_plan.simulate_test_builds('test.test builds'))

  fail_build_output = [
      api.cros_build.example('child_builder1', build_config[0]),
      api.cros_build.example('child_builder2_fail', build_config[1],
                             status='FAILURE'),
  ]

  yield (
      api.test('fail_builder') +
      properties + api.cros_build.simulated_collect_output(
          fail_build_output, step_name='test.collect') +
      api.test_plan.simulate_test_builds('test.test builds'))

  yield (api.test('fail_collect_builds') + properties + api.step_data(
      'test.collect', retcode=1))

  yield (
      api.test('fail_test_plan_run') + properties
      + api.cros_build.simulated_collect_output(builds, step_name='test.collect')
      + api.test_plan.fail_test_builds('test.test builds'))

  yield (
      api.test('fail_test_plan_collect') + properties +
      api.cros_build.simulated_collect_output(builds, step_name='test.collect')
      + api.test_plan.simulate_test_builds('test.test builds')
      + api.step_data('test.collect test results', retcode=1))

  yield (
      api.test('fail_test_plan_unit') + properties +
      api.cros_build.simulated_collect_output(builds, step_name='test.collect')
      + api.test_plan.simulate_test_builds('test.test builds')
      + api.test_plan.simulated_collect_output('test.collect test results',
                                               failure=True))
