# -*- coding: utf-8 -*-

# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for exonerating test failures."""
import traceback
from collections import defaultdict
from collections import namedtuple
from typing import Dict, List, Optional, Tuple
from typing import Set

from recipe_engine import recipe_api
from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
  TestVariantStabilityAnalysis
from PB.go.chromium.org.luci.buildbucket.proto import \
  common as common_pb2
from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
  TestVariantFailureRateAnalysis
from PB.chromiumos.test_disablement import ExcludeCfg, TestDisablementCfg
from PB.recipe_modules.chromeos.exonerate.exonerate import \
  ExonerateStats, FailedTestStats, OverallTestStats
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse

from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

CONFIG_INTERNAL_REPO = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
EXONERATION_CONFIG_BINPROTO_PATH = 'test/exoneration/generated/test_exoneration'
EXCLUDE_CONFIG_BINPROTO_PATH = 'test/exoneration/generated/excludes'
FailedTest = namedtuple('FailedTest',
                        ['name', 'board', 'build_target', 'model'])
DEFAULT_OVERALL_AUTOEX_LIMIT = 100
DEFAULT_PER_TARGET_AUTOEX_LIMIT = 20
DEFAULT_CONSISTENT_FAILURE_THRESHOLD = 6
DEFAULT_FLAKY_PERCENT_THRESHOLD = 1.0
DEFAULT_FLAKY_VERDICT_THRESHOLD = 3


class ExonerateApi(recipe_api.RecipeApi):

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._enable_exoneration = properties.enable_exoneration
    self._dry_run = properties.dry_run
    self._manual_exoneration_configs = {}
    # May contain both manual and automated exoneration configs.
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
    # Disable excludes config by default.
    self._excludes_enabled = False
    self._excludes = {}
    self._consistent_failure_threshold = properties.consistent_failure_threshold or DEFAULT_CONSISTENT_FAILURE_THRESHOLD
    self._flaky_percent_threshold = properties.flaky_percent_threshold or DEFAULT_FLAKY_PERCENT_THRESHOLD
    self._flaky_verdict_threshold = properties.flaky_verdict_threshold or DEFAULT_FLAKY_VERDICT_THRESHOLD
    self._overall_autoex_limit = properties.overall_autoex_limit or DEFAULT_OVERALL_AUTOEX_LIMIT
    self._per_target_autoex_limit = properties.per_target_autoex_limit or DEFAULT_PER_TARGET_AUTOEX_LIMIT

  @property
  def overall_autoex_limit(self):
    """Returns the max number of tests to auto exonerate."""
    return self._overall_autoex_limit

  @property
  def per_target_autoex_limit(self):
    """Returns the max number of tests to auto exonerate on a single target."""
    return self._per_target_autoex_limit

  @property
  def is_enabled(self):
    """Returns whether exoneration is enabled."""
    return self._enable_exoneration

  @property
  def manual_exoneration_configs(self) -> Dict:
    """Returns configs for the manually exonerated tests."""
    if not self._configs_loaded:
      self.load_configs()
    return self._manual_exoneration_configs

  @property
  def auto_exoneration_v2_enabled(self) -> bool:
    return 'chromeos.cq.auto.exoneration.v2.enabled' in self.m.buildbucket.build.input.experiments

  def enable_excludes(self):
    """enable excludes config's use."""
    self._excludes_enabled = True

  def fetch_config(self, mock_data=None, mock_excludes_data=None):
    """Download config files and return the extracted config protos.

    Args:
      mock_data: step_test_data for the exoneration config download step.
      mock_excludes_data: step_test_data for the excludes config download step.

    Returns: TestDisablementCfg object of the config.
    """
    if not mock_data:
      mock_data = self.test_api.fake_config_file_contents
    if not mock_excludes_data:
      mock_excludes_data = self.test_api.fake_excludes_config

    bin_proto = self.m.cros_infra_config.download_binproto(
        EXONERATION_CONFIG_BINPROTO_PATH, timeout=3 * 60,
        repo=CONFIG_INTERNAL_REPO, step_test_data=mock_data)
    exoneration_config = TestDisablementCfg.FromString(
        bin_proto) if bin_proto else TestDisablementCfg()
    bin_proto = self.m.cros_infra_config.download_binproto(
        EXCLUDE_CONFIG_BINPROTO_PATH, timeout=3 * 60, repo=CONFIG_INTERNAL_REPO,
        step_test_data=mock_excludes_data)
    excludes_config = ExcludeCfg.FromString(
        bin_proto) if bin_proto else ExcludeCfg()
    return exoneration_config, excludes_config

  def load_configs(self, mock_data=None):
    """Load configs from binary/json files."""
    self._exoneration_configs = {}
    exoneration_cfg, excludes_cfg = self.fetch_config(mock_data)

    for exoneration in exoneration_cfg.disablements:
      targets = []
      for bt_req in exoneration.dut_criteria:
        if bt_req.key == 'build_target':
          targets = bt_req.values

      self._exoneration_configs[exoneration.name] = targets

    self._manual_exoneration_configs = self._exoneration_configs.copy()
    self._excludes = {
        'tests': set(t.name for t in excludes_cfg.exclude_tests),
        'suites': set(s.name for s in excludes_cfg.exclude_suites),
    }
    self._configs_loaded = True

  def clear_failed_tests(self):
    """Clear failed_tests entries."""
    self._failed_tests = set()

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

  def print_stats(self, property_name: str) -> None:
    """Write exoneration stats to output properties & reset counts.

    Args:
      property_name: Name of the property to populate.
    """
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
    self.m.easy.set_properties_step(**{property_name: self._stats})

    # Clear the counts.
    self._stats = ExonerateStats(dry_run=self._dry_run)
    self._test_stats_map = defaultdict(int)
    self._suite_stats_map = defaultdict(int)

  def _exonerate_hw_testcase(self, test_case, build_target):
    """Exonerates a single TestCaseResult based on configs.

    Args:
      test_case(ExecuteResponse.TaskResult.TestCaseResult): test_case to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

    Returns: TestCaseResult object changed based on the decision.
    """
    test_name = self.m.exoneration_util.get_tastless_name(test_case.name)
    if self._excludes_enabled and test_name in self._excludes['tests']:
      self._add_log('Excluding {} on {} from exoneration'.format(
          test_name, build_target))
      return test_case
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

  def _exonerate_hw_test_cases(self, test_cases, build_target, board,
                               model=None):
    """Exonerates [ExecuteResponse.TaskResult.TestCaseResult] based on configs.

    Args:
      test_case([ExecuteResponse.TaskResult.TestCaseResult]): test_cases to be
        conditionally exonerated.
      build_target(str): build_target that was tested.
      board(str): board on which the test was executed.
      model(str): model on which the test was executed if explicitly requested.

    Returns: list of TestCaseResult changed based on the decision, new overall
      verdict of the tests.
    """
    new_test_cases = []
    for test_case in test_cases:
      if test_case.verdict == TaskState.VERDICT_UNSPECIFIED:
        test_case.verdict = TaskState.VERDICT_FAILED
      if test_case.verdict != TaskState.VERDICT_FAILED:
        # If test didn't fail, noop.
        new_test_cases.append(test_case)
      else:
        test_name = self.m.exoneration_util.get_tastless_name(test_case.name)
        if test_name == 'tast':
          # See http://b/246571825 for context. This test case only exists to
          # summarize failures. Remove from the list to let exoneration work
          # on actual test cases.
          continue
        self._failed_tests.add(
            FailedTest(name=test_case.name, board=board,
                       build_target=build_target, model=model or ''))
        if test_name in self._exoneration_configs:
          new_test_case = self._exonerate_hw_testcase(test_case, build_target)
          new_test_cases.append(new_test_case)
        else:
          new_test_cases.append(test_case)

    verdicts = [tc.verdict for tc in new_test_cases]
    if not verdicts or TaskState.VERDICT_FAILED in verdicts:
      new_verdict = TaskState.VERDICT_FAILED
    else:
      new_verdict = TaskState.VERDICT_PASSED
    return new_test_cases, new_verdict

  def _is_task_result_exoneration_elegible(
      self, result: ExecuteResponse.TaskResult,
      exonerate_prejob_failures: Optional[bool] = False) -> bool:
    """Returns whether the result is elegible for exoneration."""
    # Skip exoneration if it passed.
    if result.state.verdict == TaskState.VERDICT_PASSED:
      return False

    # Prejob failures are not exonerable by default.
    prejob_verdicts = [s.verdict for s in result.prejob_steps]
    if TaskState.VERDICT_FAILED in prejob_verdicts:
      return exonerate_prejob_failures

    # If all test cases have VERDICT_NO_VERDICT it is likely that none ran.
    # See b/296463877.
    if all(
        tc.verdict == TaskState.VERDICT_NO_VERDICT for tc in result.test_cases):
      return False

    return True

  def _exonerate_child_results(self, results, build_target, board, model=None):
    """Exonerates [ExecuteResponse.TaskResult] based on configs.

    Args:
      results([ExecuteResponse.TaskResult]): child results to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.
      board(str): board on which the test was executed.
      model(str): model on which the test was executed if explicitly requested.

    Returns: list of ExecuteResponse.TaskResult changed based on the decision,
      new overall status of the results.
    """
    if not results:
      # If input is empty, assume tests didn't run and return a fail result.
      return [], common_pb2.FAILURE
    filtered_results = []
    for result in results:
      if not self._is_task_result_exoneration_elegible(result):
        filtered_results.append(result)
      else:
        new_result = result
        new_test_cases, new_verdict = self._exonerate_hw_test_cases(
            result.test_cases, build_target, board, model)
        new_result.ClearField('test_cases')
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

  def exonerate_hwtests(
      self, hw_test_results: List[SkylabResult]
  ) -> Tuple[List[SkylabResult], List[str]]:
    """Exonerate the list of HW Test failures based on configs.

    Args:
      hw_test_results: list of failures from the proctor.

    Returns:
      [SkylabResult] with exonerated tests modified and [str] names of
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
          model = skylab_res.task.test.skylab_model
          display_name = str(skylab_res.task.test.common.display_name)
          suite_name = self.m.rdb_util.get_suite(display_name)
          if self._excludes_enabled and suite_name in self._excludes['suites']:
            self._add_log('Excluding {} on {} from exoneration'.format(
                suite_name, build_target))
            new_test_results.append(skylab_res)
            continue
          new_child_results, new_status = self._exonerate_child_results(
              skylab_res.child_results, build_target, board, model)
          new_skylab_res = SkylabResult(task=skylab_res.task, status=new_status,
                                        child_results=new_child_results)
          new_test_results.append(new_skylab_res)
          if new_status == common_pb2.SUCCESS:
            self._exoneration_link_map[
                display_name] = self.m.urls.get_skylab_task_url(skylab_res.task)
            exonerated_test_names.append(display_name)
            self._suite_stats_map[display_name] += 1
            self._stats.suite_count += 1
      self._print_logs(pres)
      return new_test_results, exonerated_test_names

  def is_exonerated(self, test_result):
    """Whether the test_result was exonerated.

    Args:
      test_result[TestResult]: Test result to check for.

    Returns: boolean indicating if test_result was exonerated.
    """
    test_id = self.m.exoneration_util.get_tastless_name(test_result.test_id)
    if test_id in self._exonerated_tests:
      build_target = getattr(test_result.variant, 'def')['build_target']
      if build_target in self._exonerated_tests[test_id]:
        return True

    return False

  def populate_exoneration_markdown(self):
    """Populate markdown style info about suites that were exonerated."""
    exonerated_count = len(self._exoneration_link_map)
    if exonerated_count == 0:
      return
    md_string = '{} {} exonerated\n- '.format(
        exonerated_count, 'suite' + ('s' if exonerated_count > 1 else ''))
    all_links = [
        '[{}]({})'.format(text, link)
        for text, link in self._exoneration_link_map.items()
    ]
    md_string += ', '.join(all_links)
    self.m.failures.set_exoneration_markdown(md_string)

  def get_test_variant_dict(self, test_id: str, board: str, build_target: str,
                            model: str) -> dict:
    """Create test_variant dict for LUCI Analysis from inputs.

    Args:
      test_id: Name of the test.
      board: Name of the board.
      build_target: Name of the build_target.
      model: Name of the model.

    Returns: A dict that contains the test & variant info.
    """
    # VM tests don't have suite and board info.
    # test_config is out. b/270366935
    def_map = {'build_target': build_target}
    if board:
      def_map['board'] = board
    if model:
      def_map['model'] = model
    return {'testId': test_id, 'variant': {'def': def_map}}

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
    """Get the flake count & percent of the test for the last 24 hr period.

    Args:
      interval_stats: Verdict stats of the test over interval ranges.

    Returns: Percent of verdict with flaky result in the last
      24 hr period rounded to the nearest integer.
    """
    for interval_stat in interval_stats:
      # interval_age = 1 is the last 24 hr period.
      if interval_stat.interval_age == 1:
        flaky_verdicts = interval_stat.total_run_flaky_verdicts
        non_flaky_verdicts = (
            interval_stat.total_run_expected_verdicts +
            interval_stat.total_run_unexpected_verdicts)
        total_verdicts = flaky_verdicts + non_flaky_verdicts
        flaky_percent = 0 if total_verdicts == 0 else round(
            (100 * flaky_verdicts) / total_verdicts)
        return flaky_percent

    # Adding a return statement here for pylint. We should only get here if the LUCI
    # analysis response is bad. 0 is the fallback in that case.
    return 0

  def generate_failed_test_stats(
      self, failure_rates: TestVariantFailureRateAnalysis) -> FailedTestStats:
    """Returns FailedTestStats for the given LUCI Analysis failure rates."""
    if not self._configs_loaded:
      self.load_configs()
    all_stats = []
    for failure_rate in failure_rates:
      stat = FailedTestStats()
      stat.test_id = failure_rate.test_id
      stat.build_target = self.m.rdb_util.get_build_target_from_variant(
          failure_rate.variant)
      stat.board = self.m.rdb_util.get_board_from_variant(failure_rate.variant)
      stat.model = self.m.rdb_util.get_model_from_variant(failure_rate.variant)
      # Manual exoneration's configs remove the tast prefix from test names.
      tastless_name = self.m.exoneration_util.get_tastless_name(stat.test_id)
      stat.manually_exonerated = self._is_test_name_exonerable(
          tastless_name, stat.build_target)
      stat.consistent_failure_count = (
          self.get_consistent_failure_count_from_verdicts(
              failure_rate.recent_verdicts))
      stat.flaky_verdict_percent = (
          self.get_flake_percent_from_interval_stats(
              failure_rate.interval_stats))
      flaky_verdicts = len(failure_rate.run_flaky_verdict_examples)
      # This is Browser's current algorithm. Starting with this. Might change later.
      consistently_failing = (
          stat.consistent_failure_count >= self._consistent_failure_threshold)
      was_flaky = (
          flaky_verdicts >= self._flaky_verdict_threshold and
          stat.flaky_verdict_percent >= self._flaky_percent_threshold)
      stat.automatically_exonerated = consistently_failing or was_flaky
      all_stats.append(stat)
    return all_stats

  def auto_exoneration_analysis(self, fake_data: bool = False) -> bool:
    """Analyze failed tests to see if they can be exonerated.

    Args:
      fake_data: If true, return true immediately.
        Should only be used for unittesting.

    Returns: A boolean indicating if auto exoneration was enabled without dry_run
    and did not exceed any of the limits.
    """
    if fake_data:
      return True
    if not self._enable_exoneration:
      return False
    with self.m.step.nest('Automated Exoneration Analysis') as pres:
      pres.logs['failed_tests'] = str(
          sorted(self._failed_tests, key=lambda x: x.name + x.build_target))
      if not self._failed_tests:
        pres.step_text = 'no failed tests'
        return False
      # Dry run v2: source-position-based analysis
      self.auto_exoneration_analysis_v2()
      try:
        # Convert failed tests into the format LUCI Analysis wants.
        test_variant_list = []
        for test in self._failed_tests:
          test_variant_list.append(
              self.get_test_variant_dict(test_id=test.name, board=test.board,
                                         build_target=test.build_target,
                                         model=test.model))
        test_variant_list.sort(key=lambda x: x['testId'])
        # TODO(b/272052840): See if we need to skip auto exoneration.

        failure_rates = self.m.exoneration_util.query_failure_rate(
            test_variant_list)
        pres.logs['failure_rate'] = str(
            sorted(failure_rates, key=lambda x: x.test_id))

        all_stats = self.generate_failed_test_stats(failure_rates)

        override_info = self.m.exoneration_util.override_calculation(
            all_stats, self.overall_autoex_limit, self.per_target_autoex_limit)
        overall_stats = OverallTestStats(
            failed_tests=sorted(all_stats, key=lambda x: x.test_id),
            override_info=override_info)
        pres.logs['all_stats'] = str(overall_stats)
        self.m.easy.set_properties_step(failed_test_stats=overall_stats)
        if (not self._dry_run and
            override_info.override_reason == OverallTestStats.UNSPECIFIED):
          pres.step_text = 'updating configs with automated exoneration'
          self._exoneration_configs = self.m.exoneration_util.get_updated_configs(
              all_stats, self._exoneration_configs)
          pres.logs['configs'] = self._get_printable_configs()
          return True
      except self.m.step.StepFailure:
        # Any exception in auto exoneration should not stop the orchestrator.
        pres.status = self.m.step.SUCCESS

      return False

  def _is_test_name_exonerable(
      self, test_name: str, build_target: str,
      exoneration_configs_override: Optional[Dict] = None) -> bool:
    """Checks to see if test is exonerable.

    Args:
      test_name: Name of the test.
      build_target: Name of the build_target.
      exoneration_configs_override: Alternate exoneration configs to use when
          determining if the test is exonerable.

    Returns: True if test_name is exonerable for the specific build_target.
    """
    exoneration_cfgs = exoneration_configs_override or self._exoneration_configs
    if test_name == 'tast':
      return True
    if test_name not in exoneration_cfgs:
      return False
    targets = exoneration_cfgs[test_name]
    if targets == []:
      # If targets is empty, match universally.
      return True
    return build_target in targets

  def is_hw_result_exonerable(
      self, hw_test_result: SkylabResult,
      exoneration_configs_override: Optional[Dict] = None,
      exonerate_prejob_failures: Optional[bool] = False,
      excludes_enabled_override: Optional[bool] = None) -> bool:
    """ Checks to see if hw result is exonerable.

    Args:
      hw_test_result: The skylab result to check if it is exonerable.
      exoneration_configs_override: Alternate exoneration configs to use when
          determining if the result is exonerable.
      exonerate_prejob_failures: Whether to exonerate prejob failures. These
          failures are not exonerable by default.
      excludes_enabled_override: Whether to take into account the excludes
          configs when exonerating. Overrides the module-level setting.

    Returns:
      True if and only if the result is a failure AND exonerable.
      Note that it will return False if result is a success.

    """
    if not (self._enable_exoneration or exoneration_configs_override):
      return False
    if (hw_test_result.status == common_pb2.SUCCESS or
        not hw_test_result.task.test.common.critical.value):
      # If a result is successful, technically its not exonerable.
      return False
    if not (self._configs_loaded or exoneration_configs_override):
      self.load_configs()

    excludes_enabled = self._excludes_enabled
    if excludes_enabled_override is not None:
      excludes_enabled = excludes_enabled_override

    display_name = self.m.naming.get_skylab_result_title(hw_test_result)
    suite_name = self.m.rdb_util.get_suite(display_name)
    build_target = hw_test_result.task.unit.common.build_target.name
    child_results = hw_test_result.child_results
    if not child_results:
      return False
    for result in child_results:
      if result.state.verdict == TaskState.VERDICT_PASSED:
        continue
      # Certain failure modes are not exonerable.
      if not self._is_task_result_exoneration_elegible(
          result, exonerate_prejob_failures):
        return False
      test_cases = result.test_cases
      for test_case in test_cases:
        test_name = self.m.exoneration_util.get_tastless_name(test_case.name)
        if test_case.verdict in (TaskState.VERDICT_UNSPECIFIED,
                                 TaskState.VERDICT_FAILED):
          if excludes_enabled and (suite_name in self._excludes['suites'] or
                                   test_name in self._excludes['tests']):
            return False
          if not self._is_test_name_exonerable(test_name, build_target,
                                               exoneration_configs_override):
            return False

    return True

  def get_prev_failed_now_exonerable_test_results(
      self, test_plan: GenerateTestPlanResponse,
      dry_run=False) -> List[SkylabResult]:
    """Get the tests from the previous failed runs that are now exonerable.

    Args:
      test_plan: The test plan which contains the tests for which to retrieve
      the results from previous runs.

    Returns:
      A list of exonerable HW test results.
    """

    def _get_step_text(ex_hws):
      return 'found %d suite%s' % (len(ex_hws), 's' if len(ex_hws) > 1 else '')

    def _log_results(ex_hws):
      hw_suites_names = sorted(ex_hws)
      presentation.logs['exonerable tests'] = (
          'Test Suites that previously failed '
          'but now exonerable \n'
      ) + '\n\nHW test suites:\n ' + '\n '.join(hw_suites_names)

    with self.m.step.nest(
        'get previous failed and now exonerable suites') as presentation:
      if dry_run:
        return []

      _, hw_test_results = self.m.cros_history.get_previous_test_results(
          test_plan)
      passed_tests = self.m.cros_history.get_passed_tests()

      # Exonerate HW test results.
      hw_test_results, exonerated_hw_suites = self.exonerate_hwtests(
          hw_test_results)
      exonerated_hw_suites = [
          x for x in exonerated_hw_suites if x not in passed_tests
      ]
      exonerated_hw_test_results = [
          x for x in hw_test_results
          if self.m.naming.get_skylab_result_title(x) in exonerated_hw_suites
      ]

      # Clear failed tests because they were from prev execution.
      self.clear_failed_tests()

      presentation.step_text = _get_step_text(exonerated_hw_suites)
      _log_results(exonerated_hw_suites)
      return exonerated_hw_test_results

  def auto_exoneration_analysis_v2(self, failed_tests: Set[FailedTest] = None,
                                   fake_data=None) -> None:
    """Analyze failed tests to see if they can be exonerated.

    Args:
      failed_tests: Optional override of tests to be analyzed.
        Default use self._failed_tests.
      fake_data: Mocked LUCI Analysis response data to be used for tests.
        Tuple of (List[TestVariantStabilityAnalysis], TestStabilityCriteria).
    """

    def transform_stats(
        stability: List[TestVariantStabilityAnalysis]) -> List[FailedTestStats]:
      """Convert LUCI Analaysis model to FailedTestStats."""
      if not self._configs_loaded:
        self.load_configs()
      all_stats = []
      for item in stability:
        stat = FailedTestStats()
        stat.test_id = item.test_id
        stat.build_target = self.m.rdb_util.get_build_target_from_variant(
            item.variant)
        stat.board = self.m.rdb_util.get_board_from_variant(item.variant)
        stat.model = self.m.rdb_util.get_model_from_variant(item.variant)
        stat.consistent_failure_count = item.failure_rate.unexpected_test_runs
        stat.query_position_consecutive_failure_count = item.failure_rate.consecutive_unexpected_test_runs
        stat.flaky_verdict_percent = 0 if item.flake_rate.total_verdicts == 0 else round(
            100 * item.flake_rate.run_flaky_verdicts /
            item.flake_rate.total_verdicts)
        consistently_failing = item.failure_rate.is_met
        was_flaky = item.flake_rate.is_met
        stat.automatically_exonerated = consistently_failing or was_flaky
        # Manual exoneration's configs remove the tast prefix from test names.
        tastless_name = self.m.exoneration_util.get_tastless_name(stat.test_id)
        stat.manually_exonerated = self._is_test_name_exonerable(
            tastless_name, stat.build_target)
        all_stats.append(stat)
      return all_stats

    if self.auto_exoneration_v2_enabled:
      with self.m.step.nest('Auto exoneration v2 dry run') as pres:
        try:
          if not failed_tests:
            failed_tests = self._failed_tests
          # Convert request
          test_variant_list = []
          for test in failed_tests:
            test_variant = self.get_test_variant_dict(
                test_id=test.name, board=test.board,
                build_target=test.build_target, model=test.model)
            test_variant_list.append(test_variant)
          test_variant_list.sort(key=lambda x: x['testId'])
          test_variant_position_list = self.m.exoneration_util.match_test_variants_sources(
              test_variant_list)
          all_count = len(test_variant_list)
          matched_count = len(test_variant_position_list)
          # Temporary output properties for v2 dry run debug only
          debug_dict = {
              'all_test_variants_count': all_count,
              'source_matched_count': matched_count,
              'all_matched': all_count == matched_count,
          }
          self.m.easy.set_properties_step(failed_test_stats_v2_debug=debug_dict)
          pres.logs['source matched test_variant_list'] = str(test_variant_list)
          if all_count != matched_count:
            pres.step_text = f'Only {matched_count}/{all_count} variants source matched'

          # Make call to LUCI Analysis
          stability, criteria = self.m.exoneration_util.query_stability(
              test_variant_position_list, fake_data=fake_data)
          pres.logs['stability'] = str(
              sorted(stability, key=lambda x: x.test_id))
          pres.logs['criteria'] = str(criteria)

          # Transform response to consumable stats
          all_stats = transform_stats(stability)

          # Apply override (guardrail)
          override_info = self.m.exoneration_util.override_calculation(
              all_stats, self.overall_autoex_limit,
              self.per_target_autoex_limit)
          overall_stats = OverallTestStats(
              failed_tests=sorted(all_stats, key=lambda x: x.test_id),
              override_info=override_info)
          pres.logs['all_stats'] = str(overall_stats)
          self.m.easy.set_properties_step(failed_test_stats_v2=overall_stats)
        except Exception as e:  # pylint: disable=broad-except
          pres.step_text = f'Error occurred when running auto exoneration v2: {str(e)}'
          pres.logs['exception'] = traceback.format_exc()
          pres.status = self.m.step.WARNING
