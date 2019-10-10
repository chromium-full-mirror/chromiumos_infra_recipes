# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

import structs

from PB.chromite.api.test import VmTestRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties
from PB.recipes.chromeos.test_vm import TestVmProperties
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


class CrosTestProctorApi(recipe_api.RecipeApi):

  MetaTestTuple = structs.MetaTestTuple

  def __init__(self, properties, **kwargs):
    super(CrosTestProctorApi, self).__init__(**kwargs)
    self._baseline_validation_percent = properties.baseline_validation_percent
    self._baseline_validation_count = properties.baseline_validation_count
    self._multi_request_ctp_full_enable = (
        properties.multi_request_ctp_full_enable)
    self._multi_request_ctp_cl_allowlist = (
        properties.multi_request_ctp_cl_allowlist)

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
    # Decide whether to bundle cros_test_platform requests.
    multi_req_cls = [
        gc for gc in gerrit_changes
        if gc.change in self._multi_request_ctp_cl_allowlist
    ]
    multi_req = multi_req_cls or self._multi_request_ctp_full_enable
    with self.m.step.nest('run tests') as step:
      with self.m.step.nest('schedule tests'):
        test_plan = self._get_test_plan(need_tests_builds, gerrit_changes,
                                        snapshot)

        dev = False
        if need_tests_builds:
          environment = self.m.cros_infra_config.get_builder_config(
              need_tests_builds[0].builder.builder).general.environment
          dev = environment == BuilderConfig.General.STAGING

        # We will not run tests that have already passed for this patch set.
        passed_tests = []
        if enable_history and gerrit_changes:
          passed_tests = self.m.cros_history.get_passed_tests()

        test_to_build_target_map = {}

        test_tasks = self._schedule_tests(test_plan, passed_tests,
                                          test_to_build_target_map, snapshot,
                                          multi_req=multi_req, dev=dev)

      passed_tests = []
      with self.m.step.nest('collect tests'):
        test_results = self._collect_tests(test_tasks, multi_req=multi_req)
        # Record test results.
        passed_tests = [
            self.m.naming.get_test_title(test_result)
            for test_result in (test_results.skylab + test_results.autotest_vm +
                                test_results.tast_vm + test_results.moblab_vm)
            if not self.m.failures.is_critical_test_failure(test_result)
        ]

      baseline_results = self.MetaTestTuple([], [], [], [])
      failed_test_names = ([
          self.m.naming.get_test_title(test_result)
          for test_result in (test_results.skylab + test_results.autotest_vm +
                              test_results.tast_vm)
          if self.m.failures.is_critical_test_failure(test_result)
      ])
      needs_baseline_validation = self._needs_baseline_validation(
          failed_test_names, test_plan)
      if needs_baseline_validation:
        step.presentation.step_text = (
            '{} test(s) failed. will run baseline validation'.format(
                len(failed_test_names)))
      elif failed_test_names:
        step.presentation.step_text = ('{} test(s) failed'.format(
            len(failed_test_names)))
      elif passed_tests:
        step.presentation.step_text = (
            'all tests passed. no need for baseline validation')
      else:
        step.presentation.step_text = ('no tests were necessary')

    with self.m.failures.ignore_exceptions():
      if gerrit_changes and needs_baseline_validation:
        # Start Baseline HW Verification process.
        build_targets_to_verify = set([
            test_to_build_target_map[test_name]
            for test_name in failed_test_names
        ])
        baseline_builds = []

        with self.m.step.nest('run baseline tests'):
          with self.m.step.nest('find baseline builds'):
            for build in need_tests_builds:
              build_target = self.m.cros_history.get_build_target(build)
              if build_target and build_target in build_targets_to_verify:
                baseline_builds += self.m.cros_history.get_snapshot_builds(
                    build.input.gitiles_commit, [build_target + '-snapshot'],
                    [common_pb2.SUCCESS])
          with self.m.step.nest('schedule baseline tests'):
            baseline_test_plan = self.m.cros_test_plan.generate(
                baseline_builds, gerrit_changes, snapshot)
            baseline_tasks = self._schedule_tests(
                baseline_test_plan, passed_tests, snapshot=snapshot,
                multi_req=multi_req, dev=dev)

          with self.m.step.nest('collect baseline tests'):
            baseline_results = self._collect_tests(baseline_tasks,
                                                   multi_req=multi_req)

            # Add failures here to passed_tests.
            passed_tests.extend([
                self.m.naming.get_test_title(test_result)
                for test_result in (
                    baseline_results.skylab + baseline_results.autotest_vm +
                    baseline_results.tast_vm)
                if self.m.failures.is_critical_test_failure(test_result)
            ])

    with self.m.step.nest('check test results'):
      self.m.cros_history.set_passed_tests(passed_tests)
      self.m.cros_bisect.set_test_failures(test_results.skylab,
                                           needs_baseline_validation)
      failures = self.get_test_failures(test_results, baseline_results)
    return failures

  def _get_test_plan(self, builds, gerrit_changes, snapshot):
    """Returns the test plan that should be executed for this invocation.

    Args:
      builds (list[build_pb2.Build]): builds to test.
      gerrit_changes (list[common_pb2.GerritChange]): the changes that resulted
          in the provided builds, or None.
      snapshot (GitilesCommit): Start ref of the child builds.
    """
    test_plan = self.m.cros_bisect.get_test_plan(builds)
    if test_plan:
      return test_plan
    return self.m.cros_test_plan.generate(builds, gerrit_changes, snapshot)

  def _autotest_vm_test(self, build_target):
    """Returns the autotest builder name for the given build_target."""
    return build_target.name + '-autotest-vm'

  def _tast_vm_test(self, build_target):
    """Returns the tast builder name for the given build_target."""
    return build_target.name + '-tast-vm'

  def _schedule_tests(self, test_plan, passed_tests, test_to_build_map=None,
                      snapshot=None, dev=False, multi_req=False):
    """Schedule all tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      snapshot (common_pb2.GitilesCommit): the manifest snapshot at the time
          the included builds were created.
      dev(boolean): Whether to use Skylab dev instance.

    Returns:
      MetaTestTuple of lists of the tests scheduled.
    """
    skylab_tasks = self._schedule_skylab_tests(test_plan, passed_tests,
                                               test_to_build_map, dev=dev,
                                               multi_req=multi_req)

    autotest_vm_tests = self._schedule_autotest_vm_tests(
        test_plan, passed_tests, snapshot, test_to_build_map)

    tast_vm_tests = self._schedule_tast_vm_tests(test_plan, passed_tests,
                                                 snapshot, test_to_build_map)

    moblab_vm_tests = self._schedule_moblab_vm_tests(
        test_plan, passed_tests, snapshot, test_to_build_map)
    return self.MetaTestTuple(
        skylab=skylab_tasks or [], autotest_vm=autotest_vm_tests or [],
        tast_vm=tast_vm_tests or [], moblab_vm=moblab_vm_tests or [])

  def _collect_tests(self, test_tasks, multi_req=False):
    """Collect on all tests from test_tasks.

    The tests are collected in the order: skylab, autotest_vm,
    tast_vm, moblab_vm.

    Args:
      test_tasks (MetaTestTuple): lists of tests to collect.
      multi_req (bool): whether to use multi request cros_test_platform for
          skylab requests.

    Returns:
      MetaTestTuple of lists of tests collected.
    """
    hw_results = []
    if test_tasks.skylab:
      if multi_req:
        hw_results = self.m.skylab.wait_on_suites(test_tasks.skylab)
      else:
        hw_results = self.m.skylab.wait_on_recipes(test_tasks.skylab)
    autotest_vm_results = []
    if test_tasks.autotest_vm:
      autotest_vm_results = self.m.buildbucket.collect_builds(
          [vt.id for vt in test_tasks.autotest_vm],
          step_name='collect autotest vm tests', timeout=60 * 60 * 4).values()
    tast_vm_results = []
    if test_tasks.tast_vm:
      tast_vm_results = self.m.buildbucket.collect_builds(
          [vt.id for vt in test_tasks.tast_vm],
          step_name='collect tast vm tests', timeout=60 * 60 * 4).values()
    moblab_vm_results = []
    if test_tasks.moblab_vm:
      moblab_vm_results = self.m.buildbucket.collect_builds(
          [mvt.id for mvt in test_tasks.moblab_vm],
          step_name='collect moblab vm tests', timeout=60 * 60 * 4).values()
    return self.MetaTestTuple(
        skylab=hw_results, autotest_vm=autotest_vm_results,
        tast_vm=tast_vm_results, moblab_vm=moblab_vm_results)

  def get_test_failures(self, test_results, baseline_results):
    """Logs all test failures to the UI and raises on failed tests.

    Args:
      test_results: MetaTestTuple of the tests on the changes.
      baseline_results: MetaTestTuple of the tests on the baseline images.
    Returns:
      list[Failure]: All failures discovered in the given runs filtered
          by baseline failures.
    """
    failures = self.m.failures.get_hw_test_failures(test_results.skylab,
                                                    baseline_results.skylab)
    failures += self.m.failures.get_vm_test_failures(
        test_results.autotest_vm, baseline_results.autotest_vm)
    failures += self.m.failures.get_vm_test_failures(test_results.tast_vm,
                                                     baseline_results.tast_vm)
    # TODO(evanhernandez): Include Moblab VM tests here once stable.
    return failures

  def _schedule_skylab_tests(self, test_plan, passed_tests,
                             test_to_build_map=None, dev=False,
                             multi_req=False):
    """Schedule skylab tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      dev(boolean): Whether to use Skylab dev instance.
      multi_req (bool): whether to use multi request cros_test_platform for
          skylab requests.

    Returns:
      list[SkylabTask] of the tests scheduled.
    """
    skylab_tasks = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    with self.m.step.nest('schedule hardware tests'):
      tests_to_run = []
      for unit in test_plan.hw_test_units:
        for test in unit.hw_test_cfg.hw_test:
          if test.common.display_name not in passed_tests:
            test_name = test.common.display_name
            build_target = unit.common.build_target
            test_to_build_map[test_name] = build_target.name
            tests_to_run.append(
                self.m.skylab.UnitHwTest(unit=unit, hw_test=test))
            if not multi_req:
              skylab_tasks.append(self.m.skylab.create_recipe(test, unit))
      if multi_req:
        skylab_tasks.extend(self.m.skylab.schedule_suites(tests_to_run))
    return skylab_tasks

  def _schedule_autotest_vm_tests(self, test_plan, passed_tests, snapshot,
                                  test_to_build_map=None):
    """Schedule Autotest VM Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    for unit in test_plan.vm_test_units:
      for test in unit.vm_test_cfg.vm_test:
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot,
                  builder=self._autotest_vm_test(build_target),
                  critical=test.common.critical.value,
                  properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TestVmProperties(
                              name=test_name, build_target=build_target,
                              test_harness=VmTestRequest.AUTOTEST,
                              build_payload=unit.common.build_payload,
                              expressions=['suite:' + test.test_suite])))))

    vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule autotest vm tests',
        url_title_fn=self.m.naming.get_build_title)
    return vm_tests

  def _schedule_tast_vm_tests(self, test_plan, passed_tests, snapshot,
                              test_to_build_map=None):
    """Schedule tast VM Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    for unit in test_plan.tast_vm_test_units:
      for test in unit.tast_vm_test_cfg.tast_vm_test:
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot,
                  builder=self._tast_vm_test(build_target),
                  critical=test.common.critical.value,
                  properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TestVmProperties(
                              name=test_name, build_target=build_target,
                              test_harness=VmTestRequest.TAST,
                              build_payload=unit.common.build_payload,
                              expressions=[
                                  t.test_expr for t in test.tast_test_expr
                              ])))))

    vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule tast vm tests',
        url_title_fn=self.m.naming.get_build_title)
    return vm_tests

  def _schedule_moblab_vm_tests(self, test_plan, passed_tests, snapshot,
                                test_to_build_map=None):
    """Schedule Moblab VM Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    for unit in test_plan.moblab_vm_test_units:
      for test in unit.moblab_vm_test_cfg.moblab_test:
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot, builder='moblab-vm-test',
                  critical=test.common.critical.value,
                  properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TestMoblabVmProperties(
                              name=test_name,
                              build_payload=unit.common.build_payload,
                          )))))

    moblab_vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule moblab vm tests',
        url_title_fn=self.m.naming.get_build_title)
    return moblab_vm_tests

  def _needs_baseline_validation(self, failed_results, test_plan):
    """Check if we need baseline validation for this orchestrator.

    Args:
      failed_results (list[SkylabResults]): Results of failed tests.
      test_plan (GenerateTestPlanResponse): test_plan of the orchestrator.
      percent_threshold (float): upper threshold for baseline validation.
      count_threshold (int): upper threshold of # of tests
          for baseline validation.

    Returns:
      A boolean indicating whether we need to initiate baseline
      validation.
    """
    test_count = (
        self._critical_test_count(test_plan.hw_test_units,
                                  lambda unit: unit.hw_test_cfg,
                                  lambda cfg: cfg.hw_test) +  #
        self._critical_test_count(test_plan.vm_test_units,
                                  lambda unit: unit.vm_test_cfg,
                                  lambda cfg: cfg.vm_test) +  #
        self._critical_test_count(test_plan.tast_vm_test_units,
                                  lambda unit: unit.tast_vm_test_cfg,
                                  lambda cfg: cfg.tast_vm_test))
    failure_ratio = 0
    if test_count != 0 and failed_results:
      failure_ratio = float(len(failed_results)) / test_count
      if (failure_ratio <= float(self._baseline_validation_percent) / 100 or
          len(failed_results) <= self._baseline_validation_count):
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
