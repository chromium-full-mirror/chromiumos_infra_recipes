# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

import collections
import contextlib

from recipe_engine import recipe_api


class FailuresApi(recipe_api.RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  # A failure in recipe execution.
  #
  # Fields:
  #   kind (str): Describes the kind of failure, e.g. 'build'
  #   title (str): Full title of the failure.
  #   fatal (bool): Whether or not the failure is fatal. Fatal failures cause
  #       recipes to fail when the failure is aggregated.
  Failure = collections.namedtuple('Failure', ['kind', 'title', 'fatal'])

  def __init__(self, properties, *args, **kwargs):
    super(FailuresApi, self).__init__(*args, **kwargs)
    self._disable_silences = properties.disable_silences

  def _get_silence_reason(self, step_name):
    """Query SoM to see if the step was silenced.

    Args:
      step_name (str): A full step name, e.g.
        "build results|[FAILED] chromeos.bucket.builder"

    Return:
      A str explaining the silence, or None if there is no silence on the step.
    """
    if self._disable_silences:
      return None

    # TODO(crbug.com/903414): Remove ignore exceptions once calling SoM is
    # stable.
    with self.ignore_exceptions():
      annotation = self.m.cros_som.get_annotation(step_name)

      if annotation is None:
        return None

      return self.m.cros_som.get_silence_reason(annotation)

  def _get_failures(self, kind, runs, is_failure, get_title, get_url):
    with self.m.step.nest('{} results'.format(kind)) as results_step:
      failures = []
      failed_runs = filter(is_failure, runs)
      silenced_count = 0

      for failed_run in failed_runs:
        title = get_title(failed_run)
        url = get_url(failed_run)

        # Each failure gets a substep, which helps with reporting tools such
        # as Sheriff-o-Matic.
        with self.m.step.nest('[FAILED] {}'.format(title)) as failure_step:
          failure_step.presentation.status = self.m.step.FAILURE
          failure_step.presentation.links['suite job details'] = url
          fatal = True

          silence_reason = self._get_silence_reason(
              self.m.step.active_result.name)
          if silence_reason:
            silenced_count += 1
            fatal = False

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

          failures.append(self.Failure(kind=kind, title=title, fatal=fatal))

      success_count = len(runs) - len(failed_runs)
      fail_count = len(failed_runs) - silenced_count

      if not fail_count:
        status = self.m.step.SUCCESS
        step_text = 'all {}s succeeded'.format(kind)
        if silenced_count:
          step_text += ' ({} failures were silenced)'.format(silenced_count)
      else:
        status = self.m.step.FAILURE
        step_text = '{} {}s failed, {} succeeded, {} silenced'.format(
            fail_count, kind, success_count, silenced_count)

      results_step.presentation.status = status
      results_step.presentation.step_text = step_text
      return failures

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
    # TODO(evanhernandez): Migrate this function to use _get_failures for
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

  def aggregate_failures(self, failures):
    """Returns a recipe result based on the given failures.

    Only fatal failures cause the whole recipe to fail.

    Args:
      failures (list[Failure]): All failures encountered during execution.

    Returns:
      RawResult: The recipe result, including a human-readable failure summary.
    """
    failures = [failure for failure in failures if failure.fatal]

    # If there were no fatal failures, then the recipe succeeded and there is
    # no need for a summary.
    if not failures:
      return result_pb2.RawResult(status=common_pb2.SUCCESS)

    # Otherwise, we need to create a detailed failure summary.
    failures_by_kind = collections.defaultdict(list)
    for failure in failures:
      failures_by_kind[failure.kind].append(failure)

    # The summary markdown will look roughly as follows:
    #
    # 1 build failed
    # - chromeos.cq.nami-cq
    #
    # 2 hw tests failed
    # - hw.coral.bvt-cq
    # - hw.coral.bvt-tast-cq
    # ...
    sections = []
    for kind in sorted(failures_by_kind):
      titles = sorted([failure.title for failure in failures_by_kind[kind]])
      count = len(titles)
      lines = ['{} {} failed'.format(count, kind + 's' if count > 1 else kind)]
      lines.extend(['- {}'.format(title) for title in titles])
      sections.append('\n'.join(lines))
    summary_markdown = '\n\n'.join(sections)

    return result_pb2.RawResult(status=common_pb2.FAILURE,
                                summary_markdown=summary_markdown)

  def get_build_failures(self, builds):
    """Verify all builds completed successfully.

    Args:
      builds (list[build_pb2.Build]): List of completed builds.

    Returns:
      list[Failure]: All failures discovered in the given runs.
    """
    return self._get_failures('build', builds, self.is_critical_build_failure,
                              self.m.naming.get_build_title,
                              self.m.urls.get_build_url)

  def get_hw_test_failures(self, hw_tests, baseline_hw_tests=None):
    """Logs hardware test status to UI, and raises on failed tests.

    Args:
      hw_tests (list[SkylabResult]): List of Skylab suite results.
      baseline_hw_tests (list[SkylabResult]): List of Skylab suite
        results from the baseline tests.

    Returns:
      list[Failure]: All failures discovered in the given runs.
    """
    ## TODO(dhanyaganesh): Make this function more generic.
    failed_baseline_test_names = set([
        self.m.naming.get_skylab_result_title(test)
        for test in baseline_hw_tests or []
        if self.is_critical_hw_test_failure(test)
    ])
    filtered_hw_tests = [
        test for test in hw_tests if self.m.naming.get_skylab_result_title(test)
        not in failed_baseline_test_names
    ]
    failures = self._get_failures('hw test', filtered_hw_tests,
                                  self.is_critical_hw_test_failure,
                                  self.m.naming.get_skylab_result_title,
                                  self.m.urls.get_skylab_result_url)
    if baseline_hw_tests:
      # Present, but do not fail on, baseline hardware tests.
      self._get_failures('baseline hw test', baseline_hw_tests,
                         self.is_critical_hw_test_failure,
                         self.m.naming.get_skylab_result_title,
                         self.m.urls.get_skylab_result_url)
    return failures

  def get_vm_test_failures(self, vm_tests):
    """Logs VM test status to UI, and raises on failed tests.

    Args:
      vm_tests (list[Build]): List of VM test buildbucket results.

    Returns:
      list[Failure]: All failures discovered in the given runs.
    """
    return self._get_failures('vm test', vm_tests,
                              self.is_critical_vm_test_failure,
                              self.m.naming.get_vm_test_title,
                              self.m.urls.get_build_url)

  def get_moblab_vm_test_failures(self, moblab_vm_tests):
    """Logs Moblab VM test status to UI, but does not rais on failed tests.

    Args:
      moblab_vm_tests (list[Build]): List of Moblab VM test buildbucket results.

    Returns:
      list[Failure]: All failures discovered in the given runs.
    """
    return self._get_failures('moblab vm test', moblab_vm_tests,
                              self.is_critical_moblab_vm_test_failure,
                              self.m.naming.get_moblab_vm_test_title,
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
