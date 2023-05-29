# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""
from __future__ import annotations

import collections
import contextlib
import operator

from typing import Dict, List
from dataclasses import dataclass, field

from PB.chromiumos.common import ImageType
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult


class FailuresApi(RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  # A failure in recipe execution.
  #
  # Fields:
  #   kind (str): Describes the kind of failure, e.g. 'build'
  #   title (str): Full title of the failure.
  #   link_map (str->str): title to URL map for the failed task.
  #   fatal (bool): Whether or not the failure is fatal. Fatal failures cause
  #       recipes to fail when the failure is aggregated.
  #   id (str): a unique, reproducible name for this failure. For build-type
  #       failures, this is the builder name. For test-type failures this is the
  #       display_name.
  Failure = collections.namedtuple('Failure',
                                   ['kind', 'title', 'link_map', 'fatal', 'id'])

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._exoneration_markdown = None
    self._caught_exceptions = {}

  @dataclass
  class Results():
    """A class for keeping aggregated results from executions."""

    failures: List[FailuresApi.Failure] = field(default_factory=List)
    successes: Dict[str, int] = field(default_factory=Dict)

    def add_failures(self, failures: List[FailuresApi.Failure]) -> None:
      """Append failures to the list.

      Args:
        failures (List[FailuresApi.Failure]): A List of Failure objects to
          append.
      """
      if failures:
        self.failures += failures

    def add_successes(self, successes: Dict[str, int]) -> None:
      """Update the successes numbers.

      Args:
        successes (Dict[str, int]): A Dict of success count per test kind to be
          updated with.
      """
      if successes:
        self.successes = {
            i: self.successes.get(i, 0) + successes.get(i, 0)
            for i in set(self.successes).union(successes)
        }

    def add_results(self, results: FailuresApi.Results) -> None:
      """Update the results.

      Args:
        results (Results): an object containing the list[Failure] of all
          failures discovered in the given runs and a Dict mapping a task kind
          with the number of successes.
      """
      self.add_failures(results.failures)
      self.add_successes(results.successes)

  def _proto_to_step_status(self, proto_status):
    """Convert from common_pb2.Status to api.step status.

    Args:
      status (common_pb2.Status): status of the step.

    Returns:
      str representing status as listed in step/api.py.
    """
    if proto_status == common_pb2.SUCCESS:
      return self.m.step.SUCCESS
    if proto_status == common_pb2.INFRA_FAILURE:
      return self.m.step.EXCEPTION
    return self.m.step.FAILURE

  def _present_run(self, title, link_map, status, critical=True):
    with self.m.step.nest(title) as presentation:
      if status != common_pb2.SUCCESS and not critical:
        presentation.step_text = 'failed but is not critical'
        presentation.status = self.m.step.SUCCESS
      else:
        presentation.status = self._proto_to_step_status(status)
      for link_text, link_url in link_map.items():
        presentation.links[link_text] = link_url
      return

  def _get_results(self, kind, runs, get_status, is_critical, get_title,
                   get_link_map, get_id):
    with self.m.step.nest('{} results'.format(kind)) as results_pres:
      results = self.Results(failures=[], successes={})
      failed_runs = [
          run for run in runs if get_status(run) != common_pb2.SUCCESS
      ]
      only_infra_failure = True

      for failed_run in sorted(failed_runs, key=get_title):
        title = get_title(failed_run)
        link_map = get_link_map(failed_run)
        fail_id = get_id(failed_run)
        status = get_status(failed_run)
        critical = is_critical(failed_run)

        self._present_run(title, link_map, status, critical)
        only_infra_failure &= (status == common_pb2.INFRA_FAILURE)

        if critical:
          results.failures.append(
              self.Failure(kind=kind, title=title, link_map=link_map,
                           fatal=True, id=fail_id))

      success_runs = [run for run in runs if run not in failed_runs]
      results.successes = {kind: 0}
      for success_run in sorted(success_runs, key=get_title):
        title = get_title(success_run)
        link_map = get_link_map(success_run)
        status = get_status(success_run)
        critical = is_critical(success_run)

        if critical:
          results.successes[kind] += 1

        self._present_run(title, link_map, status)

      if not results.failures:
        status = self.m.step.SUCCESS
        step_text = 'all critical {}s succeeded'.format(kind)
      else:
        status = self.m.step.EXCEPTION if only_infra_failure else self.m.step.FAILURE
        step_text = '{} {}s failed, {} succeeded'.format(
            len(failed_runs), kind, len(success_runs))

      results_pres.status = status
      results_pres.step_text = step_text
      return results

  def set_exoneration_markdown(self, markdown_txt: str):
    """Store string containing exoneration info for summary.

    Args:
      markdown_txt: String containing summary of exonerations.
    """
    self._exoneration_markdown = markdown_txt

  @contextlib.contextmanager
  def ignore_exceptions(self):
    """Catches exceptions and logs them instead.

    Should only be used temporarily to prevent new features from crashing the
    entire recipe. Remove once new feature is stable.
    """
    try:
      yield
    except Exception as e:  # pylint: disable=broad-except
      step = self.m.step('ignored exception', cmd=None)
      step.presentation.logs['caught exception'] = repr(e)
      # Update the caught_exceptions output property with error for the current step.
      self._caught_exceptions.update({".".join(self.m.step.active_result.name_tokens): repr(e)})
      self.m.easy.set_properties_step(caught_exceptions=self._caught_exceptions)

  def _set_failed_packages(self, enclosing_step, packages, compile_failure):
    """If any failed packages, set presentation and raise failure.

    Args:
      enclosing_step (step): The enclosing step to mutate.
      packages (list[tuple[chromiumos.common.PackageInfo, str]]): The failed
        packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """

    def _concat_package_markdown_link(package_info, log_text):
      # If the package did not produce a log, just return the name.
      if not log_text:
        return self.m.naming.get_package_title(package_info)

      log_name = '%s_%s_log' % (package_info.category,
                                package_info.package_name)
      log_url = self.m.urls.get_logdog_url(self.m.step.active_result, log_name)
      markdown_link = '[%s](%s)' % (
          self.m.naming.get_package_title(package_info), log_url)

      return markdown_link

    # Return early if there were no failed packages.
    if not packages:
      return

    packages.sort(key=lambda p: p[0].package_name)
    # Create top-level links to the list of failed packages as well as to the
    # Portage logs for the failed packages.
    enclosing_step.presentation.logs['list of failed packages'] = map(
        self.m.naming.get_package_title, [p[0] for p in packages])
    for p in packages:
      if not p[1]:
        continue
      enclosing_step.presentation.logs['%s/%s log' % (p[0].category,
                                                      p[0].package_name)] = p[1]

    failed_package_names = [
        self.m.naming.get_package_title(p[0]) for p in packages
    ]
    failed_packages_links = [
        _concat_package_markdown_link(p[0], p[1]) for p in packages
    ]

    if compile_failure:
      error_reason_text = 'failed compilation for'
    else:
      error_reason_text = 'failed unit tests for'

    if len(packages) == 1:
      step_text = '%s %s' % (error_reason_text, failed_package_names[0])
      failure_message = '%s %s' % (error_reason_text, failed_packages_links[0])
    else:
      step_text = '{} {} packages: {}'.format(error_reason_text, len(packages),
                                              ', '.join(failed_package_names))
      summary_lines = [
          '{} {} packages'.format(error_reason_text, len(packages))
      ]
      for p in failed_packages_links:
        summary_lines.append('- {}'.format(p))
      failure_message = self._format_summary_markdown(summary_lines)

    enclosing_step.presentation.status = self.m.step.FAILURE
    enclosing_step.presentation.step_text = step_text
    raise StepFailure(failure_message)

  def set_test_failed_packages(self, enclosing_step, packages):
    return self._set_failed_packages(enclosing_step, packages, False)

  def set_compile_failed_packages(self, enclosing_step, packages):
    return self._set_failed_packages(enclosing_step, packages, True)

  def raise_failed_image_tests(self, failed_images):
    """Display failed image tests and raise a failure.

    Displays the images that failed tests and raises a failure if there
    are failed image tests. If there are no failed image tests, a success
    message is output.

    Args:
      failed_images: (list[chromite.image.Image]): The images that failed
          tests.

    Raises:
      StepFailure: If failed_images is not empty.
    """
    with self.m.step.nest('image test results') as presentation:
      if not failed_images:
        presentation.step_text = 'all images passed'
        return

      message = '{} images failed'.format(len(failed_images))
      presentation.step_text = message
      presentation.status = self.m.step.FAILURE
      failed_types = [ImageType.Name(image.type) for image in failed_images]
      presentation.logs['list of failed images'] = failed_types
      raise StepFailure(message)

  def aggregate_failures(self, results, ignore_build_test_failures=False):
    """Returns a recipe result based on the given failures.

    Only fatal failures cause the whole recipe to fail.

    Args:
      results (Results): An object containg all failures encountered during
        execution and a dictionary mapping a test kind with the number
        of successes. Only tests considered as critical are counted.
      ignore_build_test_failures (bool): If True, we will still produce a summary
        of failures if present, but we will not set the build status to FAILURE.

    Returns:
      RawResult: The recipe result, including a human-readable failure summary.
    """

    fatal_failures = [failure for failure in results.failures if failure.fatal]

    status = common_pb2.SUCCESS if (
        (not fatal_failures) or
        ignore_build_test_failures) else common_pb2.FAILURE

    non_fatal_failures = [
        failure.kind for failure in results.failures if not failure.fatal
    ]
    exoneration_summary = self._exoneration_markdown

    non_fatal_failures_count_by_kind = collections.Counter(non_fatal_failures)
    failures_by_kind = collections.defaultdict(list)
    for failure in fatal_failures:
      failures_by_kind[failure.kind].append(failure)

    # The summary markdown will look roughly as follows:
    #
    # 1 out of 10 build failed (1 additional non-critical failure)
    # - chromeos.cq.nami-cq: <a>build page<\a>
    #
    # 2 out of 20 hw tests failed
    # - hw.coral.bvt-cq: <a>Graphics_Something<\a>
    # - hw.coral.bvt-tast-cq: <a>Cheets_SomethingElse<\a>
    # ...
    summary_lines = [exoneration_summary] if exoneration_summary else []
    for kind in sorted(failures_by_kind):
      failure_group = sorted(failures_by_kind[kind],
                             key=operator.attrgetter('title'))
      failure_count = len(failure_group)
      total_count = failure_count
      if kind in results.successes:
        total_count += results.successes[kind]

      main_line = '{} out of {} {} failed'.format(
          failure_count,
          total_count,
          kind + 's' if total_count > 1 else kind,
      )
      if kind in non_fatal_failures_count_by_kind:
        non_fatal_count = non_fatal_failures_count_by_kind[kind]
        main_line += ' ({} additional non-critical failure{})'.format(
            non_fatal_count, 's' if non_fatal_count > 1 else '')
        del non_fatal_failures_count_by_kind[kind]

      lines = [main_line]
      truncate_max = 10
      failures_to_print = failure_group[0:truncate_max]
      for failure in failures_to_print:
        line = '- {}:'.format(failure.title)
        for link_text, link_url in failure.link_map.items():
          line += ' [{}]({})'.format(link_text, link_url)
        lines.append(line)
      if failure_count > truncate_max:
        lines.append('- ...and {} others'.format(failure_count - truncate_max))
      summary_lines.extend(lines)

    for kind in non_fatal_failures_count_by_kind:
      non_fatal_count = non_fatal_failures_count_by_kind[kind]
      summary_lines.append('{} non-critical {} failed'.format(
          non_fatal_count, kind + 's' if non_fatal_count > 1 else kind))

    if 'hw test' in failures_by_kind:
      summary_lines.append('')
      summary_lines.append('📢: If this CQ attempt failed on an unrelated test, '
                           'please read go/chromeos-cq-customization-psa')

    summary_markdown = self._format_summary_markdown(summary_lines)

    return result_pb2.RawResult(status=status,
                                summary_markdown=summary_markdown)

  def _format_summary_markdown(self, summary_lines):
    """Aggregate individual failure summary lines.

    There is a 4000 byte limit on the summary_markdown field in buildbucket.
    This function ensures that we do not go over that limit when summarizing the
    failures which occurred in the build.

    Args:
      summary_lines (list[str]): Text lines to add to the summary markdown.

    Returns:
      summary_markdown (str): A markdown text that can be used to set the result
      of the step or build.
    """
    # Truncate the list of failures per section to keep the summary under
    # Buildbucket's 4000 byte limit on the summary_markdown field.
    summary_markdown = ''
    for line in summary_lines:
      if len(summary_markdown) + len(line) < 3990:
        summary_markdown += ('\n\n' + line)
      else:
        # Abruptly truncate to avoid INFRA_FAILURE.
        summary_markdown += ('\n\n...')
        break

    summary_markdown = summary_markdown.strip()
    return summary_markdown

  def get_build_results(self, builds, refresh_configs=False):
    """Verify all builds completed successfully.

    Args:
      builds (list[build_pb2.Build]): List of completed builds.
      refresh_configs (bool): Whether to update configs and adjust is_critical.

    Returns:
      A Results object containing the list[Failure] of all failures discovered
      in the given runs and a dict mapping a task kind with the number of
      successes.
    """
    get_id = lambda b: b.builder.builder
    results = self._get_results('build', builds, self.get_build_status,
                                self.m.buildbucket.is_critical,
                                self.m.naming.get_build_title,
                                self.m.urls.get_build_link_map, get_id)
    if refresh_configs:
      self.m.cros_infra_config.force_reload()
      child_configs = self.m.cros_infra_config.safe_get_builder_configs(
          [b.builder.builder for b in builds])
      results.failures = self.update_non_critical_build_failures(
          results.failures, child_configs)
    return results

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
    return self._get_results('hw test', hw_tests, self.get_hwtest_status,
                             self.is_hw_test_critical,
                             self.m.naming.get_skylab_result_title,
                             self.m.urls.get_skylab_result_link_map, get_id)

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
                  self.Failure(kind=kind, title=title, link_map=link_map,
                               fatal=True, id=title))
            else:
              presentation.step_text = 'Test not run but is not critical'
              presentation.status = self.m.step.SUCCESS
        status = self.m.step.SUCCESS
        if critical_failures:
          status = self.m.step.FAILURE
        results_pres.status = status
        results_pres.step_text = 'Build targets for tests was not built or failed building'
    return critical_failures

  def get_vm_test_results(self, vm_tests):
    """Logs VM test status to UI, and raises on failed tests.

    Args:
      vm_tests (list[Build]): List of VM test buildbucket results.

    Returns:
      A Results object containing the list[Failure] of all failures discovered
      in the given runs and a dict mapping a task kind with the number of
      successes.
    """
    get_id = self.m.naming.get_vm_test_title
    return self._get_results('vm test', vm_tests, self.get_build_status,
                             self.m.buildbucket.is_critical,
                             self.m.naming.get_vm_test_title,
                             self.m.urls.get_vm_test_link_map, get_id)

  def get_build_status(self, build):
    """Retrieve the status of the build.

    Args:
      build (Build): The buildbucket Build in question.

    Returns:
      status (common_pb2.Status) of the build.
    """
    return build.status

  def is_critical_test_failure(self, test):
    """Determine if the test is critical and has failed.

    Args:
      test (Build|SkylabResult): The test in question.

    Returns:
      bool: True if the test is critical and has failed.
    """
    if isinstance(test, build_pb2.Build):
      return self.is_critical_build_failure(test)
    if isinstance(test, SkylabResult):
      return self.is_critical_hw_test_failure(test)
    raise StepFailure('expected Build or SkylabResult,' 'got %s' % type(test))

  def get_hwtest_status(self, hw_test):
    """Get the status of the hw_test.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      status (common_pb2.STATUS) of the test.
    """
    return hw_test.status

  def is_hw_test_critical(self, hw_test):
    """Determine if the hw test was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test was critical.
    """
    return hw_test.task.test.common.critical.value

  def is_critical_build_failure(self, build):
    """Determine in the build failed and was critical.

    Args:
      build (Build): The buildbucket build in question.

    Returns:
      bool: True if the build failed and was critical.
    """
    return (self.get_build_status(build) != common_pb2.SUCCESS and
            self.m.buildbucket.is_critical(build))

  def is_critical_hw_test_failure(self, hw_test):
    """Determine if the hw test failed and was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test failed and was critical.
    """
    return (self.get_hwtest_status(hw_test) != common_pb2.SUCCESS and
            hw_test.task.test.common.critical.value)

  @contextlib.contextmanager
  def _with_step(self, step, name):
    """Returns a context with the current step, or a new one.

    Args:
      step (StepData): The current step, or None.
      name (str): The name of the step to create if there is not one.

    Returns:
      (context) with active step.
    """
    if step:
      yield step
    else:
      with self.m.step.nest(name) as new_step:
        yield new_step

  def update_non_critical_build_failures(self, failures, fresh_builder_configs,
                                         presentation=None):
    """If builders are now non-critical or removed, failures are non-fatal.

    Args:
      failures (list[Failure]): All failures encountered during execution.
      fresh_builder_configs (dict(str, BuilderConfig)): name to builder config
          for all BuilderConfigs that should have criticality checked.
      presentation (StepPresentation): Parent step presentation.  If None, a
          StepPresentation will be created.

    Returns:
      updated_failures (list[Failure]): The list of Failures with 'fatal'
          statuses possibly updated.
    """
    updated_failures = []
    new_non_critical_builds = []
    for f in failures:
      fatal = f.fatal
      if f.kind == 'build':
        if f.id in fresh_builder_configs:
          cfg = fresh_builder_configs[f.id]
          non_critical = cfg.general.critical and not cfg.general.critical.value
        else:
          # Deleted builders are non_critical.
          non_critical = True
        if f.fatal and non_critical:
          new_non_critical_builds.append(f.id)
          fatal = False
      updated_failures.append(
          self.Failure(kind=f.kind, title=f.title, link_map=f.link_map,
                       fatal=fatal, id=f.id))
    if new_non_critical_builds:
      with self._with_step(presentation, 'non-critical build check') as pres:
        pres.logs['new non-critical builders'] = new_non_critical_builds
    return updated_failures

  def update_non_critical_test_failures(self, failures, test_plan_summary,
                                        presentation=None):
    """If tests are now non-critical, failures are non-fatal.

    Args:
      failures (list[Failure]): All failures encountered during execution.
      test_plan_summary (dict{string: bool}): Map of test display name to
        criticality against which to check test failures.
      presentation (StepPresentation): Parent step presentation.  If None, a
          StepPresentation will be created.

    Returns:
      updated_failures (list[Failure]): The list of Failures with 'fatal'
        statuses possibly updated.
    """
    updated_failures = []
    new_non_critical_tests = []

    for f in failures:
      # Skip build and non-fatal failures.
      if not f.kind.endswith('test') or not f.fatal:
        updated_failures.append(f)
        continue

      # Deleted tests are considered critical. The planner may have different
      # options, and choose one test in the first plan, a second test in the
      # second plan; to err on the side of caution, assume that if a test is not
      # explicitly marked non-critical, it is still critical.
      critical = test_plan_summary.get(f.id, True)
      if not critical:
        new_non_critical_tests.append(f.id)
        updated_failures.append(
            self.Failure(kind=f.kind, title=f.title, link_map=f.link_map,
                         fatal=critical, id=f.id))
      else:
        updated_failures.append(f)

    if new_non_critical_tests:
      with self._with_step(presentation, 'non-critical test check') as pres:
        pres.logs['new non-critical tests'] = new_non_critical_tests
    return updated_failures

  def format_step_failures(self, step_failures):
    """Helper function to format the collected failures for presentation.

    Args:
      step_failures (list[Failure]): Collected error messages from exceptions.
    Returns:
      formatted markdown string for UI presentation.
    """
    markdown = ""
    if step_failures:
      lines = [
          "{} step{} failed:\n".format(
              len(step_failures), "" if len(step_failures) == 1 else "s")
      ]
      for failure in step_failures:
        lines += ["- %s\n" % failure.reason or failure.name]

      # truncate markdown to 4K to avoid INFRA_FAILURE
      markdown = lines[0]
      for line in lines[1:]:
        if len(markdown) + len(line) < 3990:
          markdown += '\n\n' + line
        else:  #pragma: nocover
          markdown += '\n\n...'
          break
    return markdown
