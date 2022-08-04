# -*- coding: utf-8 -*-

# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import six
from google.protobuf import json_format
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.chromiumos.test_disablement import TestDisablementCfg
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateStats
from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse

CONFIG_INTERNAL_REPO = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
EXONERATION_CONFIG_BINPROTO_PATH = 'test/exoneration/generated/test_exoneration'


class ExonerateApi(recipe_api.RecipeApi):

  def __init__(self, properties, **kwargs):
    super(ExonerateApi, self).__init__(**kwargs)
    self._enable_exoneration = properties.enable_exoneration
    self._dry_run = properties.dry_run
    self._exoneration_configs = {}
    self._configs_loaded = False
    self._stats = ExonerateStats(dry_run=properties.dry_run)
    # Global log store to reduce the number of steps created.
    self._global_log_lines = []

  def fetch_config(self):
    """Download config file and return the extracted config proto.

    Returns: TestDisablementCfg object of the config.
    """
    str_config = six.ensure_binary(
        self.m.cros_infra_config.download_binproto(
            EXONERATION_CONFIG_BINPROTO_PATH, timeout=3 * 60,
            repo=CONFIG_INTERNAL_REPO,
            step_test_data=self.test_api.fake_config_file_contents))
    return TestDisablementCfg.FromString(str_config)

  def _load_configs(self):
    """Load configs from binary/json files."""
    self._exoneration_configs = {}
    exoneration_cfg = self.fetch_config()

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

  def _print_logs(self, pres):
    """Print all saved logs to pres.logs and empty list after."""
    dry_run_text = 'Exoneration is running in DRY_RUN mode.\n' if self._dry_run else ''
    if not self._global_log_lines:
      pres.logs['exoneration logs'] = 'No tests were exonerated.'
    else:
      pres.logs['exoneration logs'] = (
          dry_run_text + '\n'.join(self._global_log_lines))
      self._global_log_lines = []

  def print_stats(self):
    """Write exoneration stats to output properties."""
    self.m.easy.set_properties_step(exoneration_stats=self._stats)

  def _exonerate_hw_testcase(self, test_case, build_target):
    """Exonerates a single TestCaseResult based on configs.

    Args:
      test_case(ExecuteResponse.TaskResult.TestCaseResult): test_case to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

    Returns: TestCaseResult object changed based on the decision.
    """
    targets = self._exoneration_configs[test_case.name]
    if targets == []:
      # If targets is empty, match universally.
      bt_match = True
    else:
      bt_match = build_target in targets
    if bt_match:
      self._add_log('Exonerated {} on {}'.format(test_case.name, build_target))
      self._stats.test_count += 1

    if bt_match and not self._dry_run:
      return ExecuteResponse.TaskResult.TestCaseResult(
          name=test_case.name, verdict=TaskState.VERDICT_PASSED,
          human_readable_summary=('Exonerated: ' +
                                  test_case.human_readable_summary))

    return test_case

  def _exonerate_hw_test_cases(self, test_cases, build_target):
    """Exonerates [ExecuteResponse.TaskResult.TestCaseResult] based on configs.

    Args:
      test_case([ExecuteResponse.TaskResult.TestCaseResult]): test_cases to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

    Returns: list of TestCaseResult changed based on the decision, new overall
      verdict of the tests.
    """
    if not test_cases:
      # If test_cases are empty, assume tests didn't run and return a fail verdict.
      return [], TaskState.VERDICT_FAILED

    new_test_cases = []
    for test_case in test_cases:
      if test_case.verdict != TaskState.VERDICT_FAILED:
        # If test didn't fail, noop.
        new_test_cases.append(test_case)
      else:
        if test_case.name in self._exoneration_configs:
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

  def _exonerate_child_results(self, results, build_target):
    """Exonerates [WaitTaskResult.Task] based on configs.

    Args:
      results([WaitTaskResult.Task]): child results to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

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
            result.test_cases, build_target)
        new_result.ClearField("test_cases")
        new_result.test_cases.extend(new_test_cases)
        new_result.state.verdict = new_verdict
        filtered_results.append(new_result)

    verdicts = [r.state.verdict for r in filtered_results]
    if TaskState.VERDICT_FAILED in verdicts:
      new_status = common_pb2.FAILURE
    else:
      new_status = common_pb2.SUCCESS
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
      if not self._configs_loaded:
        self._load_configs()

      for skylab_res in hw_test_results:
        if skylab_res.status == common_pb2.SUCCESS:
          # If test suite passed, do nothing.
          new_test_results.append(skylab_res)
        else:
          build_target = skylab_res.task.unit.common.build_target.name
          new_child_results, new_status = self._exonerate_child_results(
              skylab_res.child_results, build_target)
          new_skylab_res = self.m.skylab.SkylabResult(
              task=skylab_res.task, status=new_status,
              child_results=new_child_results)
          new_test_results.append(new_skylab_res)
          if new_status == common_pb2.SUCCESS:
            exonerated_test_names.append(
                str(skylab_res.task.test.common.display_name))
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
    targets = self._exoneration_configs[test_case['name']]
    if targets == []:
      # If targets is empty, match universally.
      bt_match = True
    else:
      bt_match = build_target in targets
    if bt_match:
      self._add_log('Exonerated {} on {}'.format(test_case['name'],
                                                 build_target))
      self._stats.test_count += 1
    if bt_match and not self._dry_run:
      return {'name': test_case['name'], 'verdict': 'VERDICT_PASSED'}

    return test_case

  def exonerate_vm_testcases(self, all_test_cases, build_target):
    """Exonerates VM test cases based on configs.

    Args:
      all_test_cases([Dict with predefined keys]): VM test_cases to be
        conditionally exonerated.
      build_target(str): build_target on which the test was executed.

    Returns: list of test cases modified based on configs and the new
      overall status(common_pb2.status).
    """
    if not all_test_cases:
      # If there are no test_cases, assume failure and exit.
      return [], common_pb2.FAILURE
    new_test_cases = []
    for test_case in all_test_cases:
      if (test_case['verdict'] != 'VERDICT_FAILED' or
          test_case['name'] not in self._exoneration_configs):
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
        self._load_configs()

      for build in vm_builds:
        if build.status == common_pb2.SUCCESS:
          # If the test suite passed, do nothing.
          new_vm_builds.append(build)
        elif 'all_test_cases' not in build.output.properties:
          # If the test results are missing, do nothing.
          new_vm_builds.append(build)
        else:
          new_build = build_pb2.Build()
          new_build.CopyFrom(build)
          build_target = self.m.cros_infra_config.get_build_target_name(build)
          prop_struct = build.output.properties['all_test_cases']
          all_test_cases = json_format.MessageToDict(prop_struct)
          new_test_cases, new_status = self.exonerate_vm_testcases(
              all_test_cases, build_target)
          new_build.status = new_status
          new_build.output.properties.update({'all_test_cases': new_test_cases})
          if new_status == common_pb2.SUCCESS:
            exonerated_test_names.append(self.m.naming.get_vm_test_title(build))
          new_vm_builds.append(new_build)

      self._print_logs(pres)

    return new_vm_builds, exonerated_test_names
