# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

import contextlib

from recipe_engine import recipe_api


class FailuresApi(recipe_api.RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  def _raise_failures(self, kind, runs, is_failure, get_title, get_url,
                      fatal=True):
    with self.m.step.nest('{} results'.format(kind)) as step:
      failed_runs = filter(is_failure, runs)

      if not failed_runs:
        step.presentation.step_text = 'all {}s succeeded'.format(kind)
        return

      fail_count = len(failed_runs)
      success_count = len(runs) - fail_count

      step.presentation.status = self.m.step.FAILURE
      step.presentation.step_text = '{} {}s failed, {} succeeded'.format(
          fail_count, kind, success_count)

      for run in sorted(failed_runs, key=get_title):
        title = '[{}] {}'.format('FAILED' if fatal else 'FAILED BUT IGNORED',
                                 get_title(run))
        url = get_url(run)

        # Each failure gets a substep, which helps with reporting tools such
        # as Sheriff-o-Matic.
        with self.m.step.nest(title) as failure_step:
          failure_step.presentation.status = self.m.step.FAILURE
          failure_step.presentation.links['task url'] = url

      if fatal:
        raise self.m.step.StepFailure('{} {}s failed'.format(fail_count, kind))

  @contextlib.contextmanager
  def ignore_exceptions(self):
    """Catches exceptions and logs them instead.

    Should only be used temporarily to prevent new features from crashing the
    entire recipe. Remove once new feature is stable.

    Requires `step.active_result` to be present when the exception is thrown
    (i.e. at least one step has been run at the current nested context).
    """
    try:
      yield
    except Exception as e:
      self.m.step.active_result.presentation.logs['caught exception'] = [
          repr(e)
      ]

  def raise_failed_packages(self, packages):
    """Display failed packages and raise a failure.

    Each package will be shown as a failed substep.

    Args:
      packages (list[chromiumos.common.PackageInfo]): The failed packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    # TODO(evanhernandez): Migrate this function to use _raise_failures for
    # better SoM reporting.
    with self.m.step.nest('installation results') as step:
      if not packages:
        step.presentation.step_text = 'all packages installed successfully'
        return

      message = 'failed to install {} packages'.format(len(packages))
      step.presentation.step_text = message
      step.presentation.status = self.m.step.FAILURE
      step.presentation.logs['list of failed packages'] = map(
          self.m.naming.get_package_title, packages)
      raise self.m.step.StepFailure(message)

  def raise_failed_builds(self, builds):
    """Verify all builds completed successfully.

    Args:
      builds (list[build_pb2.Build]): List of completed builds.

    Raises:
      CompositeBuildFailure containing all failed builds.
    """
    self._raise_failures('build', builds, self.is_critical_build_failure,
                         self.m.naming.get_build_title,
                         self.m.urls.get_build_url)

  def raise_failed_hw_tests(self, hw_tests):
    """Logs hardware test status to UI, and raises on failed tests.

    Args:
      hw_tests (list[SkylabResult]): List of Skylab suite results.

    Raises:
      recipe_api.StepFailure: If any tests failed.
    """
    self._raise_failures('hw test', hw_tests, self.is_critical_hw_test_failure,
                         self.m.naming.get_skylab_result_title,
                         self.m.urls.get_skylab_result_url)

  def raise_failed_vm_tests(self, vm_tests):
    """Logs VM test status to UI, and raises on failed tests.

    Args:
      vm_tests (list[Build]): List of VM test buildbucket results.

    Raises:
      recipe_api.StepFailure: If any tests failed.
    """
    self._raise_failures('vm test', vm_tests, self.is_critical_vm_test_failure,
                         self.m.naming.get_vm_test_title,
                         self.m.urls.get_build_url)

  def is_build_failure(self, build):
    """Determine if the build failed.

    Args:
      build (Build): The buildbucket Build in question.

    Returns:
      bool: True if the build failed.
    """
    return build.status != common_pb2.SUCCESS

  def is_hw_test_failure(self, hw_test):
    """Determine if the hardware test failed.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test failed.
    """
    return not hw_test.success

  def is_vm_test_failure(self, vm_test):
    """Determine if the VM test failed.

    Args:
      vm_test (Build): The buildbucket build for the VM test.

    Returns:
      bool: True if the test failed.
    """
    return self.is_build_failure(vm_test)

  def is_critical_build_failure(self, build):
    """Determine in the build failed and was critical.

    Args:
      build (Build): The buildbucket build in question.

    Returns:
      bool: True if the build failed and was critical.
    """
    return (self.is_build_failure(build) and
            self.m.buildbucket.is_critical(build))

  def is_critical_hw_test_failure(self, hw_test):
    """Determine if the vm test failed and was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test failed and was critical.
    """
    return (self.is_hw_test_failure(hw_test) and
            hw_test.task.test.common.critical.value)

  def is_critical_vm_test_failure(self, vm_test):
    """Determine if the vm test failed and was critical.

    Args:
      vm_test (Build): The buildbucket build for the VM test.

    Returns:
      bool: True if the test failed and was critical
    """
    return self.is_critical_build_failure(vm_test)
