# -*- coding: utf-8 -*-

# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import defaultdict
from collections import namedtuple
from typing import List
from google.protobuf import json_format
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
    TestVariantFailureRateAnalysis
from PB.chromiumos.test_disablement import TestDisablementCfg
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateStats
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.recipe_modules.chromeos.exonerate.exonerate import OverallTestStats
from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse

from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

CONFIG_INTERNAL_REPO = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
EXONERATION_CONFIG_BINPROTO_PATH = 'test/exoneration/generated/test_exoneration'
FailedTest = namedtuple(
    'FailedTest', ['name', 'board', 'build_target', 'suite', 'test_config'])
CONSISTENT_FAILURES_THRESHOLD = 6
FLAKE_PERCENT_THRESHOLD = 3


class ExonerateApi(recipe_api.RecipeApi):

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._enable_exoneration = properties.enable_exoneration
    self._dry_run = properties.dry_run
    self._exoneration_configs = {}
    self._configs_loaded = False
    self._stats = ExonerateStats(dry_run=properties.dry_run)
    self._exoneration_link_map = {}
    self._test_stats_map = defaultdict(int)
    self._suite_stats_map = defaultdict(int)
    self._exonerated_tests = defaultdict(set)
    self._failed_tests = set()
    # Global log store to reduce the number of steps created.
    self._global_log_lines = []

  @property
  def is_enabled(self):
    """Returns whether exoneration is enabled."""
    return self._enable_exoneration

  def fetch_config(self, mock_data=None):
    """Download config file and return the extracted config proto.

    Args:
      mock_data: step_test_data for the config download step.

    Returns: TestDisablementCfg object of the config.
    """
    if not mock_data:
      mock_data = self.test_api.fake_config_file_contents
    bin_proto = self.m.cros_infra_config.download_binproto(
        EXONERATION_CONFIG_BINPROTO_PATH, timeout=3 * 60,
        repo=CONFIG_INTERNAL_REPO, step_test_data=mock_data)
    if bin_proto:
      return TestDisablementCfg.FromString(bin_proto)
    return TestDisablementCfg()

  def get_tastless_name(self, test_name):
    """Return test_name without the tast prefix."""
    if test_name.startswith('tast.'):
      return test_name[5:]
    return test_name

  def load_configs(self, mock_data=None):
    """Load configs from binary/json files."""
    self._exoneration_configs = {}
    exoneration_cfg = self.fetch_config(mock_data)

    for exoneration in exoneration_cfg.disablements:
      targets = []
      for bt_req in exoneration.dut_criteria:
        if bt_req.key == 'build_target':
          targets = bt_req.values

      self._exoneration_configs[exoneration.name] = targets

    self._configs_loaded = True

  def _add_log(self, line):
    """Add log line (str) to global list."""
    self._global_log_lines.append(line)

  def _rdb_map_to_string(self):
    """Return exonerated tests as it will be sent to ResultDB."""
    lines = []
    for test in sorted(self._exonerated_tests.keys()):
      targets = [str(t) for t in self._exonerated_tests[test]]
      lines.append('{}:\t{}'.format(test, targets))

    return '\n'.join(lines)

  def _print_logs(self, pres):
    """Print all saved logs to pres.logs and empty list after."""
    if not self._global_log_lines:
      pres.logs['exoneration logs'] = 'No tests were exonerated.'
    else:
      pres.logs['exoneration logs'] = '\n'.join(self._global_log_lines)
      pres.logs['exonerated tests'] = self._rdb_map_to_string()
      self._global_log_lines = []

  def _get_printable_configs(self):
    """Return configs in a printable str format."""
    lines = []
    for test in sorted(self._exoneration_configs.keys()):
      targets = [str(t) for t in self._exoneration_configs[test]]
      lines.append('{}: {}'.format(test, targets))

    return lines

  def print_stats(self):
    """Write exoneration stats to output properties."""
    test_stats = [
        ExonerateStats.GranularStats(name=test,
                                     count=self._test_stats_map[test])
        for test in sorted(self._test_stats_map.keys())
    ]
    self._stats.test_stats.extend(test_stats)
    suite_stats = [
        ExonerateStats.GranularStats(name=suite,
                                     count=self._suite_stats_map[suite])
        for suite in sorted(self._suite_stats_map.keys())
    ]
    self._stats.test_stats.extend(test_stats)
    self._stats.suite_stats.extend(suite_stats)
    self.m.easy.set_properties_step(exoneration_stats=self._stats)

  def _exonerate_hw_testcase(self, test_case, build_target):
    """Exonerates a single TestCaseResult based on configs.

    Args:
      test_case(ExecuteResponse.TaskResult.TestCaseResult): test_case to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

    Returns: TestCaseResult object changed based on the decision.
    """
    test_name = self.get_tastless_name(test_case.name)
    targets = self._exoneration_configs[test_name]
    if targets == []:
      # If targets is empty, match universally.
      bt_match = True
    else:
      bt_match = build_target in targets
    if bt_match:
      self._add_log('Exonerated {} on {}'.format(test_name, build_target))
      self._stats.test_count += 1
      self._test_stats_map[test_name] += 1
      self._exonerated_tests[test_name].add(build_target)
      return ExecuteResponse.TaskResult.TestCaseResult(
          name=test_name, verdict=TaskState.VERDICT_PASSED,
          human_readable_summary=('Exonerated: ' +
                                  test_case.human_readable_summary))

    return test_case

  def _exonerate_hw_test_cases(self, test_cases, build_target, board, suite):
    """Exonerates [ExecuteResponse.TaskResult.TestCaseResult] based on configs.

    Args:
      test_case([ExecuteResponse.TaskResult.TestCaseResult]): test_cases to be
        conditionally exonerated.
      build_target(str): build_target that was tested.
      board(str): board on which the test was executed.
      suite(str): suite in which the test was executed.

    Returns: list of TestCaseResult changed based on the decision, new overall
      verdict of the tests.
    """
    if not test_cases:
      # If test_cases are empty, assume tests didn't run and return a fail verdict.
      return [], TaskState.VERDICT_FAILED

    new_test_cases = []
    for test_case in test_cases:
      if test_case.verdict == TaskState.VERDICT_UNSPECIFIED:
        test_case.verdict = TaskState.VERDICT_FAILED
      if test_case.verdict != TaskState.VERDICT_FAILED:
        # If test didn't fail, noop.
        new_test_cases.append(test_case)
      else:
        test_name = self.get_tastless_name(test_case.name)
        if test_name == 'tast':
          # See http://b/246571825 for context. This test case only exists to
          # summarize failures. Remove from the list to let exoneration work
          # on actual test cases.
          continue
        self._failed_tests.add(
            FailedTest(name=test_case.name, board=board,
                       build_target=build_target, suite=suite,
                       test_config=f'{build_target}-cq.hw.{suite}'))
        if test_name in self._exoneration_configs:
          new_test_case = self._exonerate_hw_testcase(test_case, build_target)
          new_test_cases.append(new_test_case)
        else:
          new_test_cases.append(test_case)

    verdicts = [tc.verdict for tc in new_test_cases]
    if TaskState.VERDICT_FAILED in verdicts:
      new_verdict = TaskState.VERDICT_FAILED
    else:
      new_verdict = TaskState.VERDICT_PASSED
    return new_test_cases, new_verdict

  def _exonerate_child_results(self, results, build_target, board, suite):
    """Exonerates [WaitTaskResult.Task] based on configs.

    Args:
      results([WaitTaskResult.Task]): child results to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.
      board(str): board on which the test was executed.
      suite(str): suite in which the test was executed.

    Returns: list of WaitTaskResult.Task changed based on the decision, new
      overall status of the results.
    """
    if not results:
      # If input is empty, assume tests didn't run and return a fail result.
      return [], common_pb2.FAILURE
    filtered_results = []
    for result in results:
      if result.state.verdict == TaskState.VERDICT_PASSED:
        filtered_results.append(result)
      else:
        new_result = result
        new_test_cases, new_verdict = self._exonerate_hw_test_cases(
            result.test_cases, build_target, board, suite)
        new_result.ClearField("test_cases")
        new_result.test_cases.extend(new_test_cases)
        new_result.state.verdict = new_verdict
        filtered_results.append(new_result)

    # CTP performs retries at the Autotest "test" level
    # (e.g. critical-chrome-shard-0). Therefore each test may have multiple
    # attempts represented in child_results.
    # If the test passed once, we should consider that a success.
    result_name_to_verdicts_map = {}
    for result in filtered_results:
      if result.name not in result_name_to_verdicts_map:
        result_name_to_verdicts_map[result.name] = []
      result_name_to_verdicts_map[result.name].append(result.state.verdict)

    new_status = common_pb2.SUCCESS
    for verdicts in result_name_to_verdicts_map.values():
      if TaskState.VERDICT_PASSED not in verdicts:
        new_status = common_pb2.FAILURE
        break

    return filtered_results, new_status

  def exonerate_hwtests(self, hw_test_results):
    """Exonerate the list of HW Test failures based on configs.

    Args:
      hw_test_results([Skylab_Result]): list of failures from the proctor.

    Returns:
      [Skylab_Result] with exonerated tests modified and [str] names of
      tests that should be treated as success.
    """
    if not self._enable_exoneration:
      return hw_test_results, []
    exonerated_test_names = []
    new_test_results = []
    with self.m.step.nest('exonerate hw tests') as pres:
      # Always print configs here. For debugging.
      pres.logs['configs'] = self._get_printable_configs()
      if not self._configs_loaded:
        self.load_configs()

      for skylab_res in hw_test_results:
        if (skylab_res.status == common_pb2.SUCCESS or
            not skylab_res.task.test.common.critical.value):
          # If test suite passed or is non-critical, do nothing.
          new_test_results.append(skylab_res)
        else:
          build_target = skylab_res.task.unit.common.build_target.name
          board = skylab_res.task.test.skylab_board
          suite_name = str(skylab_res.task.test.common.display_name)
          new_child_results, new_status = self._exonerate_child_results(
              skylab_res.child_results, build_target, board, suite_name)
          new_skylab_res = SkylabResult(task=skylab_res.task, status=new_status,
                                        child_results=new_child_results)
          new_test_results.append(new_skylab_res)
          if new_status == common_pb2.SUCCESS:
            link_text = '{}.{}'.format(build_target, suite_name)
            self._exoneration_link_map[
                link_text] = self.m.urls.get_skylab_task_url(skylab_res.task)
            exonerated_test_names.append(suite_name)
            self._suite_stats_map[suite_name] += 1
            self._stats.suite_count += 1
      self._print_logs(pres)
      return new_test_results, exonerated_test_names

  def exonerate_vm_testcase(self, test_case, build_target):
    """Exonerates a single test case based on configs.

    Args:
      test_case(TestCaseResult in dict form): VM test_case to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

    Returns: test case dictionary changed based on the decision.
    """
    test_name = test_case['name']
    targets = self._exoneration_configs[test_name]
    if targets == []:
      # If targets is empty, match universally.
      bt_match = True
    else:
      bt_match = build_target in targets
    if bt_match:
      self._add_log('Exonerated {} on {}'.format(test_name, build_target))
      self._stats.test_count += 1
      self._test_stats_map[test_name] += 1
      self._exonerated_tests[test_name].add(build_target)
      return {'name': test_name, 'verdict': 'VERDICT_PASSED'}

    return test_case

  def exonerate_vm_testcases(self, all_test_cases, build_target, suite):
    """Exonerates VM test cases based on configs.

    Args:
      all_test_cases([Dict with predefined keys]): Failed VM test_cases
        to be conditionally exonerated.
      build_target(str): build_target on which the test was executed.
      suite(str): suite in which the test was executed.

    Returns: list of test cases modified based on configs and the new
      overall status(common_pb2.status).
    """
    if not all_test_cases:
      # If there are no test_cases, assume failure and exit.
      return [], common_pb2.FAILURE
    new_test_cases = []
    for test_case in all_test_cases:
      test_name = test_case['name']
      self._failed_tests.add(
          FailedTest(
              name=test_case['name'],
              # board == build_target for VM tests.
              board=build_target,
              build_target=build_target,
              suite=suite,
              test_config=f'{build_target}-cq.tast_vm.{suite}'))
      if test_name not in self._exoneration_configs:
        new_test_cases.append(test_case)
      else:
        new_test_case = self.exonerate_vm_testcase(test_case, build_target)
        new_test_cases.append(new_test_case)

    verdicts = [tc['verdict'] for tc in new_test_cases]
    if 'VERDICT_FAILED' in verdicts:
      new_status = common_pb2.FAILURE
    else:
      new_status = common_pb2.SUCCESS
    return new_test_cases, new_status

  def exonerate_vmtests(self, vm_builds):
    """Exonerate the list of VM Test failures based on configs.

    Args:
      vm_builds([build_pb2.Build]): list of vm results from the proctor.

    Returns:
      [Build] with exonerated tests modified and [str] names of
      tests that should be treated as success.
    """
    if not self._enable_exoneration:
      return vm_builds, []

    exonerated_test_names = []
    new_vm_builds = []

    with self.m.step.nest('exonerate vm tests') as pres:
      if not self._configs_loaded:
        self.load_configs()

      for build in vm_builds:
        if build.status == common_pb2.SUCCESS or build.critical == common_pb2.NO:
          # If the test suite passed, do nothing.
          new_vm_builds.append(build)
        elif 'failed_test_cases' not in build.output.properties:
          # If the test results are missing, do nothing.
          new_vm_builds.append(build)
        else:
          new_build = build_pb2.Build()
          new_build.CopyFrom(build)
          build_target = self.m.cros_infra_config.get_build_target_name(build)
          suite = self.m.rdb_util.get_vm_suite(build.input.properties['name'])
          prop_struct = build.output.properties['failed_test_cases']
          all_test_cases = json_format.MessageToDict(prop_struct)
          new_test_cases, new_status = self.exonerate_vm_testcases(
              all_test_cases, build_target, suite)
          new_build.status = new_status
          new_build.output.properties.update(
              {'failed_test_cases': new_test_cases})
          if new_status == common_pb2.SUCCESS:
            suite_name = self.m.naming.get_vm_test_title(build)
            link_text = '{}.{}'.format(build_target, suite_name)
            self._exoneration_link_map[
                link_text] = self.m.buildbucket.build_url(build_id=build.id)
            exonerated_test_names.append(suite_name)
            self._suite_stats_map[suite_name] += 1
            self._stats.suite_count += 1
          new_vm_builds.append(new_build)

      self._print_logs(pres)

    return new_vm_builds, exonerated_test_names

  def is_exonerated(self, test_result):
    """Whether the test_result was exonerated.

    Args:
      test_result[TestResult]: Test result to check for.

    Returns: boolean indicating if test_result was exonerated.
    """
    test_id = self.get_tastless_name(test_result.test_id)
    if test_id in self._exonerated_tests:
      build_target = getattr(test_result.variant, 'def')['build_target']
      if build_target in self._exonerated_tests[test_id]:
        return True

    return False

  def get_exoneration_markdown(self):
    """Return markdown style info about suites that were exonerated.

    Returns: str in markdown style.
    """
    exonerated_count = len(self._exoneration_link_map)
    if exonerated_count == 0:
      return ''
    md_string = '{} {} exonerated\n- '.format(
        exonerated_count, 'suite' + ('s' if exonerated_count > 1 else ''))
    all_links = [
        '[{}]({})'.format(text, link)
        for text, link in self._exoneration_link_map.items()
    ]
    md_string += ', '.join(all_links)
    return md_string

  def get_test_variant_dict(self, test_id: str, board: str, build_target: str,
                            suite: str, test_config: str) -> dict:
    """Create test_variant dict for LUCI Analysis from inputs.

    Args:
      test_id: Name of the test.
      board: Name of the board.
      build_target: Name of the build_target.
      suite: Name of the suite.
      test_config: test_config of the test.

    Returns: A dict that contains the test & variant info.
    """
    return {
        'testId': test_id,
        'variant': {
            'def': {
                'board': board,
                'build_target': build_target,
                'suite': suite,
                'test_config': test_config
            }
        }
    }

  def get_consistent_failure_count_from_verdicts(
      self, recent_verdicts: List[TestVariantFailureRateAnalysis.RecentVerdict]
  ) -> int:
    """Get the number of failures in the last 10 independant runs from LUCI Analysis.

    Args:
      recent_verdicts: 10 most recent verdicts from LUCI Analysis.

    Returns: Number of failures in the last 10 runs.
    """
    return sum([v.has_unexpected_runs for v in recent_verdicts])

  def get_flake_percent_from_interval_stats(
      self, interval_stats: List[TestVariantFailureRateAnalysis.IntervalStats]
  ) -> int:
    """Get the flake percent of the test for the last 24 hr period.

    Args:
      interval_stats: Verdict stats of the test over interval ranges.

    Returns: Percent of verdict with unexpected or flaky result in
      the last 24 hr period rounded to the nearest integer.
    """
    for interval_stat in interval_stats:
      # interval_age = 1 is the last 24 hr period.
      if interval_stat.interval_age == 1:
        bad_verdicts = (
            interval_stat.total_run_flaky_verdicts +
            interval_stat.total_run_unexpected_verdicts)
        total_verdicts = bad_verdicts + interval_stat.total_run_expected_verdicts
        return 0 if total_verdicts == 0 else round(100 * (bad_verdicts) /
                                                   total_verdicts)

    # Adding a return statement here for pylint. We should only get here if the LUCI
    # analysis response is bad. 0 is the fallback in that case.
    return 0

  def auto_exoneration_dry_run(self) -> None:
    """Try Automatically Exonerating failed tests."""
    with self.m.step.nest('Automated Exoneration Dry-run') as pres:
      pres.logs['failed_tests'] = str(
          sorted(self._failed_tests, key=lambda x: x.name + x.build_target))
      if not self._failed_tests:
        pres.step_text = 'no failed tests'
        return
      if self._dry_run:
        # Convert failed tests into the format LUCI Analysis wants.
        test_variant_list = []
        for test in self._failed_tests:
          test_variant_list.append(
              self.get_test_variant_dict(test_id=test.name, board=test.board,
                                         build_target=test.build_target,
                                         suite=test.suite,
                                         test_config=test.test_config))
        # TODO(b/272052840): See if we need to skip auto exoneration.

        failure_rates = self.m.luci_analysis.query_failure_rate(
            test_variant_list, project='chromeos')
        pres.logs['failure_rate'] = str(failure_rates)
        all_stats = []
        for failure_rate in failure_rates:
          stat = FailedTestStats()
          stat.test_id = failure_rate.test_id
          stat.build_target = self.m.rdb_util.get_build_target_from_variant(
              failure_rate.variant)
          stat.manually_exonerated = self._is_test_name_exonerable(
              str(stat.test_id), str(stat.build_target))
          stat.consistent_failure_count = self.get_consistent_failure_count_from_verdicts(
              failure_rate.recent_verdicts)
          stat.flaky_verdict_percent = self.get_flake_percent_from_interval_stats(
              failure_rate.interval_stats)
          # This is Browser's current algorithm. Starting with this. Might change later.
          stat.automatically_exonerated = (
              stat.consistent_failure_count > CONSISTENT_FAILURES_THRESHOLD or
              stat.flaky_verdict_percent > FLAKE_PERCENT_THRESHOLD)
          all_stats.append(stat)

        overall_stats = OverallTestStats(failed_tests=all_stats)
        pres.logs['all_stats'] = str(overall_stats)
        self.m.easy.set_properties_step(failed_test_stats=overall_stats)

  def _is_test_name_exonerable(self, test_name, build_target):
    """Checks to see if test is exonerable.

    Args:
      test_name[str]: Name of the test
      build_target[str]: Name of the build_target

    Returns: True if test_name is exonerable for the specific build_target.
    """
    if test_name == 'tast':
      return True
    if test_name not in self._exoneration_configs:
      return False
    targets = self._exoneration_configs[test_name]
    if targets == []:
      # If targets is empty, match universally.
      return True
    return build_target in targets

  def is_hw_result_exonerable(self, hw_test_result) -> bool:
    """ Checks to see if hw result is exonerable.

    Args:
      hw_test_result(Skylab_Result): skylab result.

    Returns:
      True if and only if the result is a failure AND exonerable.
      Note that it will return False if result is a success.

    """
    if not self._enable_exoneration:
      return False
    if (hw_test_result.status == common_pb2.SUCCESS or
        not hw_test_result.task.test.common.critical.value):
      # If a result is successful, technically its not exonerable.
      return False
    if not self._configs_loaded:
      self.load_configs()

    build_target = hw_test_result.task.unit.common.build_target.name
    child_results = hw_test_result.child_results
    if not child_results:
      return False
    exonerated = False
    for result in child_results:
      if result.state.verdict == TaskState.VERDICT_PASSED:
        continue
      test_cases = result.test_cases
      for test_case in test_cases:
        test_name = self.get_tastless_name(test_case.name)
        if (test_case.verdict == TaskState.VERDICT_UNSPECIFIED or
            test_case.verdict == TaskState.VERDICT_FAILED):
          if not self._is_test_name_exonerable(test_name, build_target):
            return False
          exonerated = True
    return exonerated

  def is_vm_test_build_exonerable(self, vm_build):
    """Checks to see if the VM test is exonerable.

    Args:
      vm_build(build_pb2.Build): vm result from the proctor.

    Returns:
      True if and only if the result is a failure AND exonerable.
      Note that it will return False if the result itself is a success.
    """
    if not self._enable_exoneration:
      return False

    if (vm_build.status == common_pb2.SUCCESS or
        vm_build.critical == common_pb2.NO or
        'failed_test_cases' not in vm_build.output.properties):
      return False
    if not self._configs_loaded:
      self.load_configs()

    build_target = self.m.cros_infra_config.get_build_target_name(vm_build)
    prop_struct = vm_build.output.properties['failed_test_cases']
    all_test_cases = json_format.MessageToDict(prop_struct)
    if not all_test_cases:
      return False
    for test_case in all_test_cases:
      if test_case[
          'verdict'] == 'VERDICT_FAILED' and not self._is_test_name_exonerable(
              test_case['name'], build_target):
        return False
    return True
