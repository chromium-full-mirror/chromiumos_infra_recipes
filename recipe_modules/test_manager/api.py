# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Api for coordinating test execution steps."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_api


class TestManagerApi(recipe_api.RecipeApi):

  def run_tests(self, builds, step_name='run tests'):
    """Shortcut for schedule_tests + collect_tests.

    Args:
      * builds (list[build_pb2.Build]): List of builds to test.
      * step_name (str): Optional step name.

    Returns:
      list[swarming.TaskResult]
    """
    with self.m.step.nest(step_name) as step_result:
      tasks, failures = self.schedule_tests(builds)

      if failures:
        step_result.presentation.result = 'FAILURE'
        step_result.presentation.logs['test scheduling failures'] = failures

      return self.m.test_plan.collect_tests('collect test results', tasks)

  def schedule_tests(self, builds):
    """Schedule tests for successful builds.

    Args:
      * builds (list[build_pb2.Build]): List of builds to test.

    Returns:
      Tuple(list[swarming.TaskRequestMetadata], list[str])
    """
    tasks = []
    schedule_failures = []

    for build in builds:
      if build.status != common_pb2.SUCCESS:
        continue

      builder = build.builder.builder
      try:
        report_path = self.m.cros_build.download_build_report(build)

        # TODO(yshaul): add dep graph
        tasks += self.m.test_plan.test_builds('test builds - %s' % builder,
                                              report_path, dep_graph=None)
      except recipe_api.StepFailure:
        schedule_failures.append(builder)
        continue

    return tasks, schedule_failures

  def verify_tests(self, test_results):
    """Logs test status to UI, and raises on failed tests.

    Args:
      * test_results (swarming.TaskResult): List of swarming TaskResults.

    Raises:
      recipe_api.StepFailure on failing tests.
    """
    with self.m.step.nest('test results') as step_result:
      success = True

      for swarming_result in test_results:
        # We don't have a great way of highlighting failed tests.
        # Group failed tests together by prepending status.
        log_name = 'SUCCESS - ' if swarming_result.success else 'FAILURE - '
        log_name += swarming_result.name

        # Until parallel recipes materializes, dump output to step log
        step_result.presentation.logs[log_name] = [swarming_result.output]

        success &= swarming_result.success

      if not success:
        raise self.m.step.StepFailure('Failed one or more tests')
