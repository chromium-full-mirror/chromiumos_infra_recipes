# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format
from google.protobuf import duration_pb2

from recipe_engine import recipe_api

from . import structs

from PB.chromite.api.test import VmTestRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.test_vm import TestVmProperties
from PB.recipes.chromeos.tast_vm import TastVmProperties

TEST_SUMMARY_KEY = 'test_summary'


class CrosTestProctorApi(recipe_api.RecipeApi):

  MetaTestTuple = structs.MetaTestTuple

  def __init__(self, properties, **kwargs):
    super(CrosTestProctorApi, self).__init__(**kwargs)
    self.timeout = properties.timeout
    if not self.timeout.seconds:
      self.timeout = duration_pb2.Duration(seconds=7 * 60 * 60)
    self._vm_bucket = properties.vm_bucket or "staging"

  def run_proctor(self, need_tests_builds, snapshot, gerrit_changes,
                  enable_history):
    """Runs the test platform for a given bunch of builds.

    This is the entry point into the Chrome OS infra test platform via recipes.

    Args:
      need_tests_builds (list[build]): builds that are eligible for testing,
          i.e. ones that didn't suffer build failures.
      snapshot (common_pb2.GitilesCommit): the manifest snapshot at the time
          the included builds were created.
      gerrit_changes (list[common_pb2.GerritChange]): the changes that resulted
          in the provided builds, or None.
      enable_history (bool): whether to prune test history for previously
          successful tests on images with the same build inputs.

    Returns
      list[failures.Failure]: failures encountered running tests
    """
    with self.m.step.nest('run tests') as pres:
      with self.m.step.nest('schedule tests'):
        test_plan = self._get_test_plan(need_tests_builds, gerrit_changes,
                                        snapshot)

        dev = False
        if need_tests_builds:
          environment = self.m.cros_infra_config.get_builder_config(
              need_tests_builds[0].builder.builder).general.environment
          dev = environment == BuilderConfig.General.STAGING

        # We will not run tests that have already passed for this patch set.
        previously_passed_tests = set()
        is_retry = False
        if enable_history and gerrit_changes:
          is_retry = (
              self.m.cq.active and
              self.m.cros_history.is_retry(self.m.buildbucket.build))
          previously_passed_tests = self.m.cros_history.get_passed_tests()

        test_to_build_target_map = {}

        test_tasks = self.schedule_tests(test_plan, previously_passed_tests,
                                         self.timeout, test_to_build_target_map,
                                         snapshot, dev=dev, is_retry=is_retry)

      with self.m.step.nest('collect tests'):
        test_results = self._collect_tests(test_tasks, timeout=self.timeout)
        # Record test results.
        passed_test_names = []
        crit_failure_test_names = []
        non_crit_failure_test_names = []
        for test_result in (test_results.tast_vm + test_results.skylab +
                            test_results.autotest_vm):
          if test_result.status == common_pb2.SUCCESS:
            passed_test_names.append(self.m.naming.get_test_title(test_result))
          elif self.m.failures.is_critical_test_failure(test_result):
            crit_failure_test_names.append(
                self.m.naming.get_test_title(test_result))
          else:
            non_crit_failure_test_names.append(
                self.m.naming.get_test_title(test_result))
        self._set_test_summary(
            test_plan, previously_passed_tests.union(set(passed_test_names)))

      if crit_failure_test_names:
        pres.step_text = ('{} critical test(s) failed'.format(
            len(crit_failure_test_names)))
      elif non_crit_failure_test_names:
        pres.step_text = 'all critical tests passed.'
      elif passed_test_names:
        pres.step_text = ('all tests passed.')
      else:  #pragma: no cover
        # This shouldn't ever happen with multi-request
        pres.step_text = ('no tests were necessary')
        pres.properties['no_tests_needed'] = True

    with self.m.step.nest('check test results'):
      self.m.cros_history.set_passed_tests(passed_test_names)
      needs_test_bisection = self._needs_bisection(
          crit_failure_test_names, test_plan,
          self.m.cros_bisect.test_bisection_percent,
          self.m.cros_bisect.test_bisection_count)

      self.m.cros_bisect.set_test_failures(test_results.skylab,
                                           needs_test_bisection)
      failures = self.get_test_failures(test_results)
    return failures

  def _get_test_plan(self, builds, gerrit_changes, snapshot):
    """Returns the test plan that should be executed for this invocation.

    Args:
      builds (list[build_pb2.Build]): builds to test.
      gerrit_changes (list[common_pb2.GerritChange]): the changes that resulted
          in the provided builds, or None.
      snapshot (GitilesCommit): Start ref of the child builds.

    Returns:
      GenerateTestPlanResponse: the test plan.
    """
    test_plan = self.m.cros_bisect.get_test_plan(builds)
    if test_plan:
      return test_plan
    return self.m.cros_test_plan.generate(builds, gerrit_changes, snapshot)

  def _autotest_vm_test(self, build_target):
    """Returns the autotest builder name for the given build_target."""
    return build_target.name + '-autotest-vm'

  def _tast_vm_builder(self, build_target, expressions):
    """Returns the tast builder name for the given build_target and expressions."""
    if '!informational' in ''.join(expressions):
      return build_target.name + '-direct-tast-vm'
    else:
      return build_target.name + '-tast-vm-informational'

  def schedule_tests(self, test_plan, passed_tests, timeout,
                     test_to_build_map=None, snapshot=None, dev=False,
                     is_retry=False):
    """Schedule all tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      timeout (Duration): Timeout in duration_pb2.Duration.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      snapshot (common_pb2.GitilesCommit): the manifest snapshot at the time
          the included builds were created.
      dev(boolean): Whether to use Skylab dev instance.
      is_retry (bool): Whether this is a CQ retry.

    Returns:
      MetaTestTuple of lists of the tests scheduled.
    """
    skylab_tasks = self._schedule_skylab_tests(test_plan, passed_tests, timeout,
                                               test_to_build_map, is_retry)
    autotest_vm_tests = self._schedule_autotest_vm_tests(
        test_plan, passed_tests, snapshot, test_to_build_map, is_retry)
    tast_vm_tests = self._schedule_tast_vm_tests(test_plan, passed_tests,
                                                 snapshot, test_to_build_map,
                                                 is_retry)

    return self.MetaTestTuple(skylab=skylab_tasks or [],
                              autotest_vm=autotest_vm_tests or [],
                              tast_vm=tast_vm_tests or [])

  def _collect_tests(self, test_tasks, timeout):
    """Collect on all tests from test_tasks.

    The tests are collected in the order: skylab, autotest_vm,
    tast_vm.

    Args:
      test_tasks (MetaTestTuple): lists of tests to collect.
      timeout (Duration): Timeout in duration_pb2.Duration.

    Returns:
      MetaTestTuple of lists of tests collected.
    """
    hw_results = self.m.skylab.wait_on_suites(test_tasks.skylab, timeout)
    autotest_vm_results = self.m.buildbucket.collect_builds(
        [vt.id for vt in test_tasks.autotest_vm],
        step_name='collect autotest vm tests',
        timeout=int(timeout.seconds)).values()
    tast_vm_results = self.m.buildbucket.collect_builds(
        [vt.id for vt in test_tasks.tast_vm], step_name='collect tast vm tests',
        timeout=int(timeout.seconds)).values()
    return self.MetaTestTuple(skylab=hw_results,
                              autotest_vm=autotest_vm_results,
                              tast_vm=tast_vm_results)

  def get_test_failures(self, test_results):
    """Logs all test failures to the UI and raises on failed tests.

    Args:
      test_results: MetaTestTuple of the tests on the changes.
    Returns:
      list[Failure]: All failures discovered in the given run.
    """
    failures = self.m.failures.get_hw_test_failures(test_results.skylab)
    failures += self.m.failures.get_vm_test_failures(test_results.autotest_vm)
    failures += self.m.failures.get_vm_test_failures(test_results.tast_vm)
    return failures

  def _schedule_skylab_tests(self, test_plan, passed_tests, timeout,
                             test_to_build_map=None, is_retry=False):
    """Schedule skylab tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      timeout (Duration): Timeout in duration_pb2.Duration.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      is_retry (bool): Whether this is a CQ retry.
      dev(boolean): Whether to use Skylab dev instance.

    Returns:
      list[SkylabTask] of the tests scheduled.
    """
    skylab_tasks = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    with self.m.step.nest('schedule hardware tests'):
      tests_to_run = []
      hw_build_targets = set()
      for unit in test_plan.hw_test_units:
        for test in unit.hw_test_cfg.hw_test:
          # Do not run non-critical tests on retries.
          if is_retry and not test.common.critical.value:
            continue
          if test.common.display_name not in passed_tests:
            test_name = test.common.display_name
            build_target = unit.common.build_target
            test_to_build_map[test_name] = build_target.name
            tests_to_run.append(
                self.m.skylab.UnitHwTest(unit=unit, hw_test=test))
            hw_build_targets.add(build_target.name)
      if tests_to_run:
        skylab_tasks.extend(
            self.m.skylab.schedule_suites(tests_to_run, timeout))
      self.m.easy.set_properties_step(
          hw_test_build_targets=len(hw_build_targets))
      self.m.easy.set_properties_step(hw_test_suites=len(tests_to_run))
    return skylab_tasks

  def _schedule_autotest_vm_tests(self, test_plan, passed_tests, snapshot,
                                  test_to_build_map=None, is_retry=False):
    """Schedule Autotest VM Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      is_retry (bool): Whether this is a CQ retry.

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    for unit in test_plan.vm_test_units:
      for test in unit.vm_test_cfg.vm_test:
        # Do not run non-critical tests on retries.
        if is_retry and not test.common.critical.value:
          continue
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot,
                  builder=self._autotest_vm_test(build_target),
                  bucket=self._vm_bucket, critical=test.common.critical.value,
                  properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TestVmProperties(
                              name=test_name, build_target=build_target,
                              test_harness=VmTestRequest.AUTOTEST,
                              build_payload=unit.common.build_payload,
                              expressions=['suite:' + test.test_suite]))),
                  tags=self._tags_for_child_build()))

    vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule autotest vm tests',
        url_title_fn=self.m.naming.get_build_title)
    return vm_tests

  def _schedule_tast_vm_tests(self, test_plan, passed_tests, snapshot,
                              test_to_build_map=None, is_retry=False):
    """Schedule tast VM Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      is_retry (bool): Whether this is a CQ retry.

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map

    for unit in test_plan.direct_tast_vm_test_units:
      for test in unit.tast_vm_test_cfg.tast_vm_test:
        # Do not run non-critical tests on retries.
        if is_retry and not test.common.critical.value:
          continue
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          expressions = [t.test_expr for t in test.tast_test_expr]
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot,
                  builder=self._tast_vm_builder(build_target, expressions),
                  bucket=self._vm_bucket, critical=test.common.critical.value,
                  properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TastVmProperties(
                              name=test_name, build_target=build_target,
                              build_payload=unit.common.build_payload,
                              expressions=expressions))),
                  tags=self._tags_for_child_build()))
    vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule tast vm tests',
        url_title_fn=self.m.naming.get_build_title)
    return vm_tests

  def _needs_bisection(self, failed_results, test_plan, percent_threshold,
                       count_threshold):
    """Check if we need bisection.

    Check if we need bisection of the results per the bisection constraints.

    Args:
      failed_results (list[SkylabResults]): Results of failed tests.
      test_plan (GenerateTestPlanResponse): test_plan of the orchestrator.
      percent_threshold (float): upper threshold for test bisection.
      count_threshold (int): upper threshold of # of tests
          for test bisection.

    Returns:
      A boolean indicating whether we need to initiate bisection
    """
    test_count = (
        self._critical_test_count(test_plan.hw_test_units, lambda unit: unit.
                                  hw_test_cfg, lambda cfg: cfg.hw_test) +
        self._critical_test_count(test_plan.vm_test_units, lambda unit: unit.
                                  vm_test_cfg, lambda cfg: cfg.vm_test) +
        self._critical_test_count(
            test_plan.direct_tast_vm_test_units, lambda unit: unit.
            tast_vm_test_cfg, lambda cfg: cfg.tast_vm_test))
    failure_ratio = 0
    if test_count != 0 and failed_results:
      failure_ratio = float(len(failed_results)) / test_count
      if (failure_ratio <= float(percent_threshold) / 100 or
          len(failed_results) <= count_threshold):
        return True

    return False

  def _critical_test_count(self, units, cfg_func, tests_func):
    """Returns the count of critical tests within `units`.

    Args:
      units: (list[HwTestUnit|VmTestUnit|TastVmTestUnit]): Units to count the
          critical tests within.
      cfg_func: (lambda): Lambda function that takes a unit from units and
          returns the *test_cfg field.
      tests_func: (lambda): Lambda function that takes the *test_cfg field and
          returns the *test field holding the list of tests.

    Returns:
      An integer count of the critical tests with `units`.
    """
    count = 0
    for unit in units:
      for test in tests_func(cfg_func(unit)):
        if test.common.critical and test.common.critical.value:
          count += 1
    return count

  def _set_test_summary(self, test_plan, passed_test_names):
    """Saves a summary of the test plan to the build output properties.

    Args:
      test_plan (GenerateTestPlanResponse): The test plan.
      passed_test_names (list[str]): The names of the passed tests.
    """
    # Use cases:
    # * CQ test and build planning.
    # * Assist analysis of test results by dashboards with access to the
    #   buildbucket tables.
    test_summary = (
        self._extract_test_summary(
            test_plan.hw_test_units, lambda unit: unit.hw_test_cfg, lambda cfg:
            cfg.hw_test, passed_test_names) + self._extract_test_summary(
                test_plan.vm_test_units, lambda unit: unit.vm_test_cfg, lambda
                cfg: cfg.vm_test, passed_test_names) +
        self._extract_test_summary(
            test_plan.direct_tast_vm_test_units, lambda unit: unit.
            tast_vm_test_cfg, lambda cfg: cfg.tast_vm_test, passed_test_names))

    self.m.easy.set_properties_step(**{TEST_SUMMARY_KEY: test_summary})

  def _extract_test_summary(self, units, cfg_func, tests_func,
                            passed_test_names):
    """Returns a summary of the tests within `units`.

    Args:
      units (list[HwTestUnit|VmTestUnit|TastVmTestUnit]): Units to count the
          critical tests within.
      cfg_func (lambda): Lambda function that takes a unit from units and
          returns the *test_cfg field.
      tests_func (lambda): Lambda function that takes the *test_cfg field and
          returns the *test field holding the list of tests.
      passed_test_names (list[str]): The names of the passed tests.

    Returns:
      list[dict]: A summary of tests, one item per test.
    """
    result = []
    for unit in units:
      for test in tests_func(cfg_func(unit)):
        name = test.common.display_name
        status = 'SUCCESS' if name in passed_test_names else 'FAILURE'
        critical = test.common.critical and test.common.critical.value
        # This is extensible to other fields beyond criticality if needed in
        # future (did the test pass previously, did it pass this time, etc.).
        result.append(dict(name=name, critical=critical, status=status))
    return result

  def _with_props_for_child_build(self, properties):
    """Merge 'properties' and 'api.cq.props_for_child_build'.

    Should be used to insert 'props_for_child_build' into properties being passed
    to a Buildbucket request.

    Args:
      api (RecipeApi): See RunSteps documentation.
      properties (dict): A dictionary of properties.

    Returns:
      The merged dict.
    """
    properties.update(self.m.cq.props_for_child_build)
    return properties

  def _tags_for_child_build(self):
    """Tags to add to created child builds."""
    bb_tags = dict(parent_buildbucket_id=str(self.m.buildbucket.build.id))
    return self.m.cros_tags.tags(**bb_tags)
