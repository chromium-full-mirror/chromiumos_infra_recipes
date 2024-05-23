# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""
from __future__ import annotations

import collections
import contextlib
import datetime
import math
import operator
import re

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from google.protobuf import json_format

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFailureAttribute, FaultAttributedBuildTarget
from PB.recipe_modules.chromeos.failures.failures import PackageFailure

from recipe_engine.engine_types import StepPresentation
from recipe_engine.recipe_api import RecipeApi

from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

class FailuresApi(RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  @dataclass
  class Failure:
    """A failure in recipe execution.

    Fields:
      kind: Describes the kind of failure, e.g. 'build'
      title: Full title of the failure.
      link_map: title to URL map for the failed task.
      fatal: Whether or not the failure is fatal. Fatal failures cause
          recipes to fail when the failure is aggregated.
      id: a unique, reproducible name for this failure. For build-type
          failures, this is the builder name. For test-type failures this is the
          display_name.
      type: Type of the failure.
      failure_reason: The reason for the failure.
    """
    kind: str
    title: str
    link_map: Dict[str, str]
    fatal: bool
    id: str
    type: bb_common_pb2.Status = bb_common_pb2.FAILURE
    failure_reason: Optional[str] = None

  # Test kind for hw tests.
  HW_TEST = 'hw test'

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._failure_truncate_max = 10
    self._exoneration_markdown = None
    self._caught_exceptions = {}
    self._test_variant_to_fault_attribute = collections.defaultdict(
        lambda: None)

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

  def _proto_to_step_status(self, proto_status: bb_common_pb2.Status):
    """Convert from bb_common_pb2.Status to api.step status.

    Args:
      status: The status of the step.

    Returns:
      str representing status as listed in step/api.py.
    """
    if proto_status == bb_common_pb2.SUCCESS:
      return self.m.step.SUCCESS
    if proto_status == bb_common_pb2.INFRA_FAILURE:
      return self.m.step.EXCEPTION
    return self.m.step.FAILURE

  def _present_run(self, title, link_map, status, critical=True):
    with self.m.step.nest(title) as presentation:
      if status != bb_common_pb2.SUCCESS and not critical:
        presentation.step_text = 'failed but is not critical'
        presentation.status = self.m.step.SUCCESS
      else:
        presentation.status = self._proto_to_step_status(status)
      for link_text, link_url in link_map.items():
        presentation.links[link_text] = link_url
      return

  # TODO(b/327255136): Generalize this to other failures.
  def _get_build_failure_reason(self, failed_build) -> Optional[str]:
    """Returns the reason the image builder failed."""
    output_dict = json_format.MessageToDict(failed_build.output.properties)
    package_failures = [
        json_format.ParseDict(x, PackageFailure())
        for x in output_dict.get('package_failures', [])
    ]
    # If there are multiple package failures in a build, they should have all
    # failed in the same phase, but we'll verify anyway.
    # TODO(b/327255136): Start with builds that have package failures.
    failed_phases = {p.phase for p in package_failures}
    if len({p.phase for p in package_failures}) != 1:
      return None
    phase = 'compilation' if failed_phases.pop(
    ) == PackageFailure.Phase.COMPILE else 'unit tests'
    packages = ', '.join(
        sorted([
            f'{package_failure.package.category}/{package_failure.package.package_name}'
            for package_failure in package_failures
        ]))

    fault_attribution_text = ''
    if all((package_failure.snapshot_comparison ==
            CqFailureAttribute.MATCHING_FAILURE_FOUND)
           for package_failure in package_failures):
      fault_attribution_text = ' (failure also seen on snapshot builds)'
    elif all(package_failure.affected_by_changes
             for package_failure in package_failures):
      fault_attribution_text = ' (affected by the CLs in the CQ run)'
    return f'failed {phase} for {packages}{fault_attribution_text}'

  def _get_results(self, kind, runs, get_status, is_critical, get_title,
                   get_link_map, get_id, build_detailed_kind = None):
    with self.m.step.nest('{} results'.format(build_detailed_kind or kind)) as results_pres:
      results = self.Results(failures=[], successes={})
      non_critical_build_results = self.Results(failures=[], successes={})

      failed_runs = [
          run for run in runs if get_status(run) != bb_common_pb2.SUCCESS
      ]
      only_infra_failure = True

      for failed_run in sorted(failed_runs, key=get_title):
        title = get_title(failed_run)
        link_map = get_link_map(failed_run)
        fail_id = get_id(failed_run)
        status = get_status(failed_run)
        critical = is_critical(failed_run)
        failure_reason = self._get_build_failure_reason(
            failed_run) if kind == 'build' else None

        self._present_run(title, link_map, status, critical)
        only_infra_failure &= (status == bb_common_pb2.INFRA_FAILURE)

        if critical:
          results.failures.append(
              self.Failure(kind=kind, title=title, link_map=link_map,
                           fatal=True, id=fail_id, type=status,
                           failure_reason=failure_reason))
        elif build_detailed_kind:
          non_critical_build_results.failures.append(
              self.Failure(kind=kind, title=title, link_map=link_map,
                           fatal=False, id=fail_id,
                           failure_reason=failure_reason))

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

      if results.failures or non_critical_build_results.failures:
        s = 's' if len(failed_runs) > 1 else ''
        step_text = '{} {}{} failed, {} succeeded'.format(
            len(failed_runs), kind, s, len(success_runs))
        status = self.m.step.EXCEPTION if only_infra_failure else self.m.step.FAILURE
      else:
        if build_detailed_kind:
          detailed_kind = build_detailed_kind
        else:
          detailed_kind = 'critical {}'.format(kind)
        step_text = 'all {}s succeeded'.format(detailed_kind)
        status = self.m.step.SUCCESS

      results_pres.status = status
      results_pres.step_text = step_text
      return results

  def set_exoneration_markdown(self, markdown_txt: str):
    """Store string containing exoneration info for summary.

    Args:
      markdown_txt: String containing summary of exonerations.
    """
    self._exoneration_markdown = markdown_txt

  def set_test_variant_to_fault_attribute(self,
      test_variant_to_fault_attribute: Dict[Tuple[str, str, str],
      FaultAttributedBuildTarget]):
    """Sets dictionary information for test variant to the corresponding
    fault attribute.

    Args:
      test_variant_to_fault_attribute: defaultdict of tuples of the format:
      (test_id, build_target, model), to fault attribution.
    """
    self._test_variant_to_fault_attribute = test_variant_to_fault_attribute

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
      self._caught_exceptions.update({'.'.join(self.m.step.active_result.name_tokens): repr(e)})
      self.m.easy.set_properties_step(caught_exceptions=self._caught_exceptions)

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

    status = bb_common_pb2.SUCCESS

    # Set the status to INFRA_FAILURE if all failures are INFRA_FAILUREs.
    # Infra failures generally indicate issues not caused by the user's changes.
    # However, if there are any failures not marked as INFRA_FAILURE, the status should
    # be set to FAILURE, indicating that there are actionable items for the user.
    if fatal_failures and not ignore_build_test_failures:
      if all(failure.type == bb_common_pb2.INFRA_FAILURE
             for failure in fatal_failures):
        status = bb_common_pb2.INFRA_FAILURE
      else:
        status = bb_common_pb2.FAILURE

    exoneration_summary = self._exoneration_markdown

    failures_by_kind = collections.defaultdict(list)
    for failure in fatal_failures:
      failures_by_kind[failure.kind].append(failure)

    summary_lines = [exoneration_summary] if exoneration_summary else []
    for kind in sorted(failures_by_kind):
      failure_group = sorted(failures_by_kind[kind],
                             key=operator.attrgetter('title'))
      failure_count = len(failure_group)
      total_count = failure_count
      if kind in results.successes:
        total_count += results.successes[kind]

      if kind == self.HW_TEST:
        lines = self.aggregate_hw_test_failures(failure_group)
      else:
        lines = self.aggregrate_failure_group(kind, failure_group,
                                              failure_count, total_count)

      if failure_count > self._failure_truncate_max:
        lines.append('- ...and {} others'.format(failure_count - self._failure_truncate_max))
      summary_lines.extend(lines)

    if self.HW_TEST in failures_by_kind and self.m.cv.active:
      summary_lines.append('')
      summary_lines.append('📢: If this CQ attempt failed on an unrelated test, '
                           'please read go/chromeos-cq-customization-psa')

    summary_markdown = self.format_summary_markdown(summary_lines)

    return result_pb2.RawResult(status=status,
                                summary_markdown=summary_markdown)

  def aggregrate_failure_group(self, kind: str, failure_group: List[Failure],
                               failure_count: int,
                               total_count: int) -> List[str]:
    """Returns aggregate failure markdown text.

    Args:
      kind: The failure kind.
      failure_group: List of all the failures for the specific kind.
      failure_count: Number of failures
      total_count: Number of all entries

    Returns:
      List of summary markdown lines.
    """

    # This summary markdown section will look roughly as follows:
    #
    # 2 out of 10 build failed (1 additional non-critical failure)
    # - asurada-cq: <a>build page<\a>
    # - atlas-cq: <a>build page<\a>
    # ...
    main_line = '{} out of {} {} failed'.format(
        failure_count,
        total_count,
        kind + 's' if total_count > 1 else kind,
    )

    reason_to_failure_map = collections.defaultdict(list)
    for f in failure_group:
      reason_to_failure_map[f.failure_reason].append(f)

    lines = []
    # TODO(b/327255136): Do at most 2 unique failure reasons as we play around
    # with space.
    failure_reasons_count = len(reason_to_failure_map.keys())
    if (None not in reason_to_failure_map and 0 < failure_reasons_count <= 2):
      # Distribute the lines given to the "kind" across the number of reasons.
      # keeping in mind that summarizing each reason also takes up a line.
      failures_per_reason = max(
          (math.floor((self._failure_truncate_max - failure_reasons_count) /
                      failure_reasons_count)), 1)

      for reason, failures in reason_to_failure_map.items():
        main_line = f'{len(failures)} out of {total_count} {kind}s {reason}'
        lines.append(main_line)
        failures_to_print = failures[0:failures_per_reason]
        for failure in failures_to_print:
          line = '- {}:'.format(failure.title)
          for link_text, link_url in failure.link_map.items():
            line += ' [{}]({})'.format(link_text, link_url)
          lines.append(line)
    else:
      lines = [main_line]
      failures_to_print = failure_group[0:self._failure_truncate_max]
      for failure in failures_to_print:
        line = '- {}:'.format(failure.title)
        for link_text, link_url in failure.link_map.items():
          line += ' [{}]({})'.format(link_text, link_url)
        lines.append(line)

    return lines

  def aggregate_hw_test_failures(self,
                                 hw_test_failures: List[Failure]) -> List[str]:
    """Returns aggregate test failure markdown text for HW tests,
    distinguishing between test and shard / suite failures.

    Args:
      hw_test_failures: List of all the hw test failures.

    Returns:
      List of summary markdown lines.
    """

    # This summary markdown section will look roughly as follows:
    #
    # 3 hw tests failed. 1 hw test suite failed with incomplete results (1 additional non-critical failure)
    # - brya-cq.hw.cq-medium
    #     - <a>tast.firmware.something</a>
    #     - <a>tast.firmware.somethingElse</a>
    #     - <a>cq-medium-shard-1 - provisioning_failed</a>
    # - zork-cq.hw.cq-medium
    #     - <a>tast.firmware.something</a>
    # ...

    main_line = self.get_test_failure_main_line(hw_test_failures)
    lines = [main_line]
    failures_to_print = hw_test_failures[:self._failure_truncate_max]

    for failure in failures_to_print:
      line = '- {}'.format(failure.title)
      lines.append(line)
      for link_text, link_url in failure.link_map.items():
        line = '    - [{}]({})'.format(link_text, link_url)
        line += self.get_test_fault_attribution_text(failure.title, link_text)
        lines.append(line)

    return lines

  def get_test_fault_attribution_text(self, target_identifier: str, test_id: str) -> str:
    """Returns the fault attribution text of a summary markdown line.

    Args:
      target_identifier: The title of the failure, consisting of build_target
      name, suite name and optionally a model name.
      test_id: The ID of the test.

    Returns:
      Fault attribution text for a summary line.
    """
    target_identifier_parts = target_identifier.split('.')
    build_target = re.sub(r'-cq$', '', target_identifier_parts[0])
    # The target identifier for hw tests without models is typically of the
    # format: build_target-cq.hw.test_id. When there is a model present,
    # it's: build_target-cq.model.hw.test_id. We can assume that the second
    # component of the string is the model if the component size is larger than
    # 3
    model = target_identifier_parts[1] if len(target_identifier_parts) > 3 else ''
    index = (test_id, build_target, model)
    fault_attribute = self._test_variant_to_fault_attribute[index]
    if not fault_attribute:
      return ''

    fault_attribution_text = ' | {} failure already present as of [{}]({})'
    if fault_attribute.snapshot_comparison_fault_attribution == CqFailureAttribute.MATCHING_FAILURE_FOUND:
      failure_type = 'identical'
    elif fault_attribute.snapshot_comparison_fault_attribution == CqFailureAttribute.DIFFERING_FAILURE_FOUND:
      failure_type = 'different'
    else:
      return ''

    comparison_build_start_datetime = datetime.datetime.fromtimestamp(fault_attribute.comparison_snapshot.source_started_unix_timestamp, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    milo_link = 'https://ci.chromium.org/ui/b/{}/test-results?q=ExactID:{}'.format(fault_attribute.comparison_snapshot.source_build_id, test_id)

    return fault_attribution_text.format(failure_type, comparison_build_start_datetime, milo_link)

  def get_test_failure_main_line(self, failure_group: List[Failure]) -> str:
    """Returns the main line of the summary markdown.

    Args:
      failure_group: List of all the failures for the specified kind.

    Returns:
      Main line of the summary markdown.
    """
    kind = self.HW_TEST
    # This regex works on the assumption that suite / shard failures should have
    # a reason associated e.g. tast.fingerprint-cq (timed out while running).
    shard_pattern = r'^\b\S+\b\s+.+$'

    shard_failure_count = 0
    test_failure_count = 0
    for failure in failure_group:
      if len(failure.link_map.items()) == 0:
        shard_failure_count += 1

      for link_text, _ in failure.link_map.items():
        if re.match(shard_pattern, link_text):
          shard_failure_count += 1
        else:
          test_failure_count += 1

    main_line = ''
    if test_failure_count > 0:
      main_line += '{} {} failed'.format(
          test_failure_count,
          kind + 's' if test_failure_count > 1 else kind,
      )

    if shard_failure_count > 0:
      if main_line:
        main_line += '. '
      main_line += '{} {} suite{} failed with incomplete results'.format(
          shard_failure_count,
          kind,
          's' if shard_failure_count > 1 else '',
      )

    return main_line

  def format_summary_markdown(self, summary_lines):
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

  def get_build_results(self, builds, relevant_child_builder_names=None):
    """Verify all builds completed successfully.

    Args:
      builds (list[build_pb2.Build]): List of completed builds.
      relevant_child_builder_names (list(str)): List of relevant child builder
        names.

    Returns:
      A Results object containing the list[Failure] of all failures discovered
      in the given runs and a dict mapping a task kind with the number of
      successes.
    """
    get_id = lambda b: b.builder.builder
    kind = 'build'
    with self.m.step.nest('{} results'.format(kind)):
      categorized_builds = {}
      for b in builds:
        if relevant_child_builder_names and b.builder.builder in relevant_child_builder_names:
          rel = 'relevant'
        else:
          rel = 'irrelevant'
        if self.m.buildbucket.is_critical(b):
          criticality = 'critical'
        else:
          criticality = 'non-critical'

        categorized_builds.setdefault('{} {}'.format(rel, criticality), []).append(b)

      all_results = self.Results(failures=[], successes={})
      for detail, build in categorized_builds.items():
        results = self._get_results(kind, build, self.get_build_status,
                                    self.m.buildbucket.is_critical,
                                    self.m.naming.get_build_title,
                                    self.m.urls.get_build_link_map, get_id,
                                    '{} {}'.format(detail, kind))
        all_results.failures += results.failures
        if results.successes:
          all_results.successes = {
            i: all_results.successes.get(i, 0) + results.successes.get(i, 0)
            for i in set(all_results.successes).union(results.successes)
          }

    return all_results

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
    return self._get_results(self.HW_TEST, hw_tests, self.get_hwtest_status,
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

  def get_build_status(self, build: build_pb2.Build) -> bb_common_pb2.Status:
    """Retrieve the status of the build."""
    return build.status

  def is_critical_test_failure(self, test):
    """Determine if the test is critical and has failed.

    Args:
      test (SkylabResult): The test in question.

    Returns:
      bool: True if the test is critical and has failed.
    """
    return self.is_critical_hw_test_failure(test)

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

  def is_critical_build_failure(self, build):
    """Determine in the build failed and was critical.

    Args:
      build (Build): The buildbucket build in question.

    Returns:
      bool: True if the build failed and was critical.
    """
    return (self.get_build_status(build) != bb_common_pb2.SUCCESS and
            self.m.buildbucket.is_critical(build))

  def is_critical_hw_test_failure(self, hw_test):
    """Determine if the hw test failed and was critical.

    Args:
      hw_test (SkylabResult): The hardware test result in question.

    Returns:
      bool: True if the test failed and was critical.
    """
    return (self.get_hwtest_status(hw_test) != bb_common_pb2.SUCCESS and
            hw_test.task.test.common.critical.value)

  def update_non_critical_build_failures(self, failures: List[Failure],
                                         fresh_builder_configs: Dict[str, BuilderConfig],
                                         presentation: Optional[StepPresentation] = None) -> List[Failure]:
    """If builders are now non-critical or removed, failures are non-fatal.

    Args:
      failures: All failures encountered during execution.
      fresh_builder_configs: name to builder config for all BuilderConfigs that
        for all BuilderConfigs that should have criticality checked.
      presentation: Parent step presentation.  If None, a StepPresentation will
        be created.

    Returns:
      The list of Failures with 'fatal' statuses possibly updated.
    """
    updated_failures = []
    new_non_critical_builds = []
    for f in failures:
      fatal = f.fatal
      if f.kind == 'build':
        if f.id in fresh_builder_configs:
          cfg = fresh_builder_configs[f.id]
          non_critical = cfg.general.critical and not cfg.general.critical.value
        if f.fatal and non_critical:
          new_non_critical_builds.append(f.id)
          fatal = False
      updated_failures.append(
          self.Failure(kind=f.kind, title=f.title, link_map=f.link_map,
                       fatal=fatal, id=f.id, type=f.type,
                       failure_reason=f.failure_reason))
    if new_non_critical_builds:
      presentation.logs['new non-critical builders'] = new_non_critical_builds
    return updated_failures

  def format_step_failures(self, step_failures):
    """Helper function to format the collected failures for presentation.

    Args:
      step_failures (list[Failure]): Collected error messages from exceptions.
    Returns:
      formatted markdown string for UI presentation.
    """
    markdown = ''
    if step_failures:
      lines = [
          '{} step{} failed:\n'.format(
              len(step_failures), '' if len(step_failures) == 1 else 's')
      ]
      for failure in step_failures:
        lines += ['- %s\n' % failure.reason or failure.name]

      # truncate markdown to 4K to avoid INFRA_FAILURE
      markdown = lines[0]
      for line in lines[1:]:
        if len(markdown) + len(line) < 3990:
          markdown += '\n\n' + line
        else:  #pragma: nocover
          markdown += '\n\n...'
          break
    return markdown
