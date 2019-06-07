# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import json_format

from recipe_engine import recipe_api


class FailuresApi(recipe_api.RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  def raise_failed_packages(self, packages):
    """Display failed packages and raise a failure.

    Each package will be shown as a failed substep.

    Args:
      packages (list[chromiumos.common.PackageInfo]): The failed packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    with self.m.step.nest('installation results') as step:
      if not packages:
        step.presentation.step_text = 'all packages installed successfully'
        return

      packages_str = ', '.join(
          ['{}/{}'.format(p.category, p.package_name) for p in packages])
      step.presentation.step_text = 'failed to install: {}'.format(packages_str)
      step.presentation.status = self.m.step.FAILURE
      raise self.m.step.StepFailure(
          '{} packages failed to install'.format(len(packages)))

  def raise_failed_builds(self, builds):
    """Verify all builds completed successfully.

    Args:
      * builds (list[build_pb2.Build]): List of completed builds.

    Raises:
      CompositeBuildFailure containing all failed builds.
    """
    with self.m.step.nest('build results') as step:
      step.presentation.logs['buildbucket build dump'] = map(str, builds)
      failed_builds = filter(self.is_critical_build_failure, builds)

      if not failed_builds:
        step.presentation.step_text = 'all builds succeeded'
        return

      fail_count = len(failed_builds)
      success_count = len(builds) - fail_count

      step.presentation.status = self.m.step.FAILURE
      step.presentation.step_text = '{} builds failed, {} succeeded'.format(
          fail_count, success_count)

      for build in failed_builds:
        url = self.m.buildbucket.build_url(build_id=build.id)
        title = '[FAILED] {}'.format(self.m.naming.get_build_title(build))
        step.presentation.links[title] = url

      raise self.m.step.StepFailure('{} builds failed'.format(fail_count))

  def raise_failed_hw_tests(self, hw_tests):
    """Logs hardware test status to UI, and raises on failed tests.

    Args:
      * hw_tests (list[SkylabResult]): List of Skylab suite results.

    Raises:
      recipe_api.StepFailure: If any tests failed.
    """
    with self.m.step.nest('hw test results') as step:
      failed_hw_tests = filter(self.is_critical_hw_test_failure, hw_tests)

      if not failed_hw_tests:
        step.presentation.step_text = 'all hw tests passed'
        return

      fail_count = len(failed_hw_tests)
      success_count = len(hw_tests) - fail_count

      step.presentation.status = self.m.step.FAILURE
      step.presentation.step_text = '{} tests failed, {} succeeded'.format(
          fail_count, success_count)

      for failed_hw_test in failed_hw_tests:
        title = '[FAILED] {}'.format(
            failed_hw_test.task.test.common.display_name)
        step.presentation.links[title] = failed_hw_test.task.url

      raise self.m.step.StepFailure('{} hw tests failed'.format(fail_count))

  def raise_failed_vm_tests(self, vm_tests):
    """Logs VM test status to UI, and raises on failed tests.

    Args:
      * vm_tests (list[Build]): List of VM test buildbucket results.

    Raises:
      recipe_api.StepFailure: If any tests failed.
    """
    with self.m.step.nest('vm test results') as step:
      failed_vm_tests = filter(self.is_critical_vm_test_failure, vm_tests)

      if not failed_vm_tests:
        step.presentation.step_text = 'all vm tests passed'
        return

      fail_count = len(failed_vm_tests)
      success_count = len(vm_tests) - fail_count

      step.presentation.step_text = '{} tests failed, {} succeeded'.format(
          fail_count, success_count)
      step.presentation.status = self.m.step.FAILURE

      for failed_vm_test in failed_vm_tests:
        properties = json_format.MessageToDict(failed_vm_test.output.properties)
        title = '[FAILED] {}'.format(properties['name'])
        url = self.m.buildbucket.build_url(build_id=failed_vm_test.id)
        step.presentation.links[title] = url

      raise self.m.step.StepFailure('{} vm tests failed'.format(fail_count))

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
