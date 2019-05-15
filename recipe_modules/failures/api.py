# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_api


class CompositeBuildFailure(recipe_api.StepFailure):

  def __init__(self, name_or_reason, builds, result=None):
    self.builds = builds
    super(CompositeBuildFailure, self).__init__(name_or_reason, result=result)

  def reason_message(self):
    return "{}: {}".format(
        self.name,
        "\n".join([str(build.id) for build in self.builds]))  # pragma: no cover

  def __str__(self):  # pragma: nocover
    return "One or more Step Failures in %s" % self.name


class FailuresApi(recipe_api.RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  def raise_failed_packages(self, failed_packages):
    """Display failed packages and raise a failure.

    Each package will be shown as a failed substep.

    Args:
      packages (list[chromiumos.common.PackageInfo]): The failed packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    if not failed_packages:
      return
    with self.m.step.nest('failed packages'):
      for failed_package in failed_packages:
        step = self.m.step(failed_package.package_name, None)
        step.presentation.status = self.m.step.FAILURE
    raise self.m.step.StepFailure(
        'Failed to install %d packages.' % len(failed_packages))


  def verify_builds(self, builds):
    """Verify all builds completed successfully.

    Args:
      * builds (list[build_pb2.Build]): List of completed builds.

    Raises:
      CompositeBuildFailure containing all failed builds.
    """
    with self.m.step.nest('verify builds') as step:
      step.presentation.logs['all_builds'] = [str(b) for b in builds]
      failed_builds = [
          build for build in builds if self._is_critical_failure(build)
      ]

      if failed_builds:
        presentation = self.m.step.active_result.presentation
        presentation.status = self.m.step.FAILURE
        presentation.step_text = 'One or more child builders failed:'

        for build in failed_builds:
          build_url = self.m.buildbucket.build_url(build_id=build.id)
          build_title = self.m.naming.get_build_title(build)
          presentation.links[build_title] = build_url
        # TODO(crbug.com/950061): Do we still need to raise an exception if the
        # status is FAILURE above?
        raise CompositeBuildFailure('One or more child builders failed',
                                    failed_builds)


  def verify_tests(self, test_results):
    """Logs test status to UI, and raises on failed tests.

    Args:
      * test_results (swarming.TaskResult): List of swarming TaskResults.

    Raises:
      recipe_api.StepFailure on failing tests.
    """
    with self.m.step.nest('test results') as step_result:
      failure_count = 0
      for swarming_result in test_results:
        if not swarming_result.success:
          failure_count += 1
          # We don't have a great way of highlighting failed tests.
          log_name = 'FAILURE - {}'.format(swarming_result.name)
          # Until parallel recipes materializes, dump output to step log
          step_result.presentation.logs[log_name] = [swarming_result.output]
      step_result.presentation.step_text = (
          '{} succeeded, {} failed'.format(
              len(test_results)-failure_count, failure_count))
      if failure_count > 0:
        raise self.m.step.StepFailure('Failed one or more tests')


  def _is_critical_failure(self, build):
    """Checks if the status was not SUCCESS and the build was critical.

    Args:
      * build (Build proto): The completed build to check.
    """
    return (build.status != common_pb2.SUCCESS
            and self.m.buildbucket.is_critical(build))
