# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Api for coordinating test execution steps."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import json_format as jsonpb

from recipe_engine import recipe_api


class TestManagerApi(recipe_api.RecipeApi):

  def run_tests(self, builds, step_name='run tests'):
    """Shortcut for schedule_tests + collect_tests.

    Args:
      * builds (list or generator of build_pb2.Build]): Builds to test.
      * step_name (str): Optional step name.

    Returns:
      list[swarming.TaskResult]
    """
    with self.m.step.nest(step_name):
      tasks = self.m.test_plan.test_builds('test builds', list(builds))
      return self.m.test_plan.collect_tests('collect test results', tasks)

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
