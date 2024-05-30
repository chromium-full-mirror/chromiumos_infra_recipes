# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising e2e test failures and presenting them."""

from RECIPE_MODULES.chromeos.failures.api import Failure
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

from recipe_engine.recipe_api import RecipeApi


class TestFailuresApi(RecipeApi):
  """A module for presenting test failures."""

  # Test kind for hw tests.
  HW_TEST = 'hw test'

  def __init__(self, **kwargs):
    super().__init__(**kwargs)

  def get_hw_test_results(self, hw_tests):
    """Logs hardware test status to UI, and raises on failed tests.

    Args:
      hw_tests (list[SkylabResult]): List of Skylab suite results.

    Returns:
      A Results object containing the list[Failure] of all failures discovered
      in the given runs and a dict mapping a task kind with the number of
      successes.
    """
    get_id = self.m.naming.get_skylab_result_title
    return self.m.failures.get_results(self.HW_TEST, hw_tests,
                                       self.get_hwtest_status,
                                       self.is_hw_test_critical,
                                       self.m.naming.get_skylab_result_title,
                                       self.m.urls.get_skylab_result_link_map,
                                       get_id)

  def get_additional_hw_test_not_run_failures(self, not_runnable_addtnl_tests):

    critical_failures = []
    if not_runnable_addtnl_tests:
      kind = 'additional test not run'
      critical_failures = []
      with self.m.step.nest('{}'.format(kind)) as results_pres:

        for nr in not_runnable_addtnl_tests:
          title = nr.common.display_name
          link_map = {}

          critical = nr.common.critical.value
          with self.m.step.nest(title) as presentation:
            if critical:
              presentation.step_text = 'Test not run and is critical'
              presentation.status = self.m.step.FAILURE
              critical_failures.append(
                  Failure(kind=kind, title=title, link_map=link_map, fatal=True,
                          id=title))
            else:
              presentation.step_text = 'Test not run but is not critical'
              presentation.status = self.m.step.SUCCESS
        status = self.m.step.SUCCESS
        if critical_failures:
          status = self.m.step.FAILURE
        results_pres.status = status
        results_pres.step_text = 'Build targets for tests was not built or failed building'
    return critical_failures

  def is_critical_test_failure(self, test):
    """Determine if the test is critical and has failed.

    Args:
      test (SkylabResult): The test in question.

    Returns:
      bool: True if the test is critical and has failed.
    """
    return (self.get_hwtest_status(test) != bb_common_pb2.SUCCESS and
            test.task.test.common.critical.value)

  def get_hwtest_status(self, hw_test: SkylabResult) -> bb_common_pb2.Status:
    """Get the status of the hw_test."""
    return hw_test.status

  def is_hw_test_critical(self, hw_test):
    """Determine if the hw test was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test was critical.
    """
    return hw_test.task.test.common.critical.value
