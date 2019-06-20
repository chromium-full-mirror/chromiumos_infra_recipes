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

  def _get_silence_reason(self, step_name):
    """Query SoM to see if the step was silenced.

    Args:
      step_name (str): A full step name, e.g.
        "build results|[FAILED] chromeos.bucket.builder"

    Return:
      A str explaining the silence, or None if there is no silence on the step.
    """
    # TODO(crbug.com/903414): Remove ignore exceptions once calling SoM is
    # stable.
    with self.ignore_exceptions():
      annotation = self.m.cros_som.get_annotation(step_name)

      if not annotation:
        return None

      if self.m.time.ms_since_epoch() < annotation.snooze_time_ms:
        return 'step failure is snoozed by Sheriff-o-Matic.'

      if annotation.bugs:
        return 'step failure has bugs linked by Sheriff-o-Matic.'

      return None

  def _raise_failures(self, kind, runs, is_failure, get_title, get_url,
                      fatal=True):
    with self.m.step.nest('{} results'.format(kind)) as step:
      fail_count = 0
      silenced_count = 0

      for run in runs:
        if is_failure(run):
          title = '[{}] {}'.format('FAILED' if fatal else 'FAILED BUT IGNORED',
                                   get_title(run))
          url = get_url(run)

          # Each failure gets a substep, which helps with reporting tools such
          # as Sheriff-o-Matic.
          with self.m.step.nest(title) as failure_step:
            failure_step.presentation.status = self.m.step.FAILURE
            failure_step.presentation.links['task url'] = url

            silence_reason = self._get_silence_reason(
                self.m.step.active_result.name)
            if silence_reason:
              silenced_count += 1

              # Sheriff-o-Matic monitors failed steps, so we cannot modify the
              # step name because it is silenced. For example, imagine the step
              # "build results|[FAILED] chromeos.bucket.builder" is failing and
              # silenced in SoM. If in the next run we change the step name to
              # "build results|[FAILED BUT SILENCED] chromeos.bucket.builder",
              # there will be a new (unsilenced) failure, and the old (silenced)
              # failure will disappear from SoM.
              failure_step.presentation.logs['silence reason'] = [
                  silence_reason
              ]
            else:
              fail_count += 1

      if not fail_count:
        step_text = 'all {}s succeeded'.format(kind)

        if silenced_count:
          step_text += ' ({} failures were silenced)'.format(silenced_count)

        step.presentation.step_text = step_text
        return

      success_count = len(runs) - fail_count - silenced_count

      step.presentation.status = self.m.step.FAILURE
      step.presentation.step_text = '{} {}s failed, {} succeeded, {} silenced'.format(
          fail_count, kind, success_count, silenced_count)

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

  def raise_failed_moblab_vm_tests(self, moblab_vm_tests):
    """Logs Moblab VM test status to UI, but does not rais on failed tests.

    TODO(evanhernandez): Raise on failure, once tests are stable.

    Args:
      moblab_vm_tests (list[Build]): List of Moblab VM test buildbucket results.
    """
    self._raise_failures('moblab vm test', moblab_vm_tests,
                         self.is_critical_moblab_vm_test_failure,
                         self.m.naming.get_moblab_vm_test_title,
                         self.m.urls.get_build_url, fatal=False)

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

  def is_moblab_vm_test_failure(self, moblab_vm_test):
    """Determine if the VM test failed.

    Args:
      moblab_vm_test (Build): The buildbucket build for the Moblab VM test.

    Returns:
      bool: True if the test failed.
    """
    return self.is_build_failure(moblab_vm_test)

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

  def is_critical_moblab_vm_test_failure(self, moblab_vm_test):
    """Determine if the vm test failed and was critical.

    Args:
      moblab_vm_test (Build): The buildbucket build for the Moblab VM test.

    Returns:
      bool: True if the test failed and was critical
    """
    return self.is_critical_build_failure(moblab_vm_test)
