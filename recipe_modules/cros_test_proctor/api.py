# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromite.api.test import VmTestRequest
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties
from PB.recipes.chromeos.test_vm import TestVmProperties
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


class CrosTestProctorApi(recipe_api.RecipeApi):

  def run_proctor(self, need_tests_builds, completed_builds, snapshot,
                  gerrit_changes, enable_history, baseline_validation_percent,
                  baseline_validation_count):
    """Runs the test platform for a given bunch of builds.

    This is the entry point into the Chrome OS infra test platform via recipes.

    Args:
      need_tests_builds (list[build]): builds that are eligible for testing,
          i.e. ones that didn't suffer build failures.
      completed_builds (list[build]): all builds related to this proctor run,
          including builds that failed at build-time.
      snapshot (common_pb2.GitilesCommit): the manifest snapshot at the time
          the included builds were created.
      gerrit_changes (list[common_pb2.GerritChange]): the changes that resulted
          in the provided builds, or None.
      enable_history (bool): whether to prune test history for previously
          successful tests on images with the same build inputs.
      baseline_validation_percent (float): ∈[0,100], the threshold for the
          portion of failed tests to total tests below which baseline
          validation gets triggered.
      baseline_validation_count (int): >=0, the threshold for the number of
          failed tests below which baseline validation gets triggered.

    Returns
      list[failures.Failure]: failures encountered running tests
    """
    with self.m.step.nest('run tests'):
      with self.m.step.nest('schedule tests'):
        test_plan = self._get_test_plan(need_tests_builds, snapshot)

        # We will not run tests that have already passed for this patch set.
        passed_tests = []
        if enable_history and gerrit_changes:
          passed_tests = self.m.cros_history.get_passed_tests()

        test_to_build_target_map = {}

        skylab_tasks = self._schedule_skylab_tests(test_plan, passed_tests,
                                                   test_to_build_target_map)

        vm_tests = self._schedule_autotest_vm_tests(
            test_plan, passed_tests, snapshot, test_to_build_target_map)

        tast_vm_tests = self._schedule_tast_vm_tests(
            test_plan, passed_tests, snapshot, test_to_build_target_map)
        vm_tests += tast_vm_tests

        moblab_vm_tests = self._schedule_moblab_vm_tests(
            test_plan, passed_tests, snapshot, test_to_build_target_map)

      with self.m.step.nest('collect tests'):
        hw_results = []
        if skylab_tasks:
          hw_results = self.m.skylab.wait_tasks(skylab_tasks)
        vm_results = []
        if vm_tests:
          vm_results = self.m.buildbucket.collect_builds(
              [vt.id for vt in vm_tests], step_name='collect vm tests',
              timeout=60 * 60 * 4).values()
        moblab_vm_results = []
        if moblab_vm_tests:
          moblab_vm_results = self.m.buildbucket.collect_builds(
              [mvt.id for mvt in moblab_vm_tests],
              step_name='collect moblab vm tests',
              timeout=60 * 60 * 4).values()
        # Record test results.
        passed_tests = [
            hw_result.task.test.common.display_name
            for hw_result in hw_results
            if not self.m.failures.is_hw_test_failure(hw_result)
        ]
        passed_tests.extend([
            self.m.naming.get_vm_test_title(vm_result)
            for vm_result in vm_results
            if not self.m.failures.is_vm_test_failure(vm_result)
        ])
        passed_tests.extend([
            self.m.naming.get_moblab_vm_test_title(moblab_vm_result)
            for moblab_vm_result in moblab_vm_results
            if not self.m.failures.is_moblab_vm_test_failure(moblab_vm_result)
        ])

    baseline_hw_results = []
    baseline_vm_results = []
    failed_test_names = ([
        hw_result.task.test.common.display_name
        for hw_result in hw_results
        if self.m.failures.is_hw_test_failure(hw_result)
    ] + [
        self.m.naming.get_vm_test_title(vm_result)
        for vm_result in vm_results
        if self.m.failures.is_vm_test_failure(vm_result)
    ])

    with self.m.failures.ignore_exceptions():
      if gerrit_changes and self._needs_baseline_validation(
          failed_test_names, test_plan, baseline_validation_percent,
          baseline_validation_count):
        # Start Baseline HW Verification process.
        build_targets_to_verify = set([
            test_to_build_target_map[test_name]
            for test_name in failed_test_names
        ])
        baseline_builds = []
        for build in completed_builds:
          # Assuming that completed_builds have build_targets.
          build_target = self.m.cros_history.get_build_target(build)
          if build_target and build_target in build_targets_to_verify:
            baseline_builds += self.m.cros_history.get_snapshot_builds(
                build.input.gitiles_commit, [build_target + '-snapshot'],
                [common_pb2.SUCCESS])
        with self.m.step.nest('run baseline tests'):
          with self.m.step.nest('schedule baseline tests'):
            baseline_test_plan = self.m.cros_test_plan.generate(
                baseline_builds, snapshot.id)
            baseline_skylab_tasks = self._schedule_skylab_tests(
                baseline_test_plan, passed_tests, bb=True)
            baseline_vm_tests = self._schedule_autotest_vm_tests(
                baseline_test_plan, passed_tests, snapshot)
            baseline_vm_tests += self._schedule_tast_vm_tests(
                baseline_test_plan, passed_tests, snapshot)
          with self.m.step.nest('collect baseline tests'):
            if baseline_skylab_tasks:
              baseline_hw_results = self.m.skylab.wait_tasks(
                  baseline_skylab_tasks, bb=True)
              # Add failures here to passed_tests.
              passed_tests.extend([
                  hw_result.task.test.common.display_name
                  for hw_result in baseline_hw_results
                  if self.m.failures.is_hw_test_failure(hw_result)
              ])
            if baseline_vm_tests:
              baseline_vm_results = self.m.buildbucket.collect_builds(
                  [vt.id for vt in baseline_vm_tests],
                  step_name='collect baseline vm tests',
                  timeout=60 * 60 * 4).values()
              # Add failures here to passed_tests.
              passed_tests.extend([
                  self.m.naming.get_vm_test_title(vm_result)
                  for vm_result in baseline_vm_results
                  if self.m.failures.is_vm_test_failure(vm_result)
              ])

    self.m.cros_history.set_passed_tests(passed_tests)

    # Verify builds/tests in a deferred context so that all failures appear.
    failures = []
    with self.m.step.nest('check test results'):
      self.m.cros_bisect.set_test_failures(hw_results)
      failures.extend(
          self.m.failures.get_hw_test_failures(hw_results, baseline_hw_results))
      failures.extend(
          self.m.failures.get_vm_test_failures(vm_results, baseline_vm_results))
      # TODO(evanhernandez): Include Moblab VM tests here once stable.
      # Also, add Moblab to baseline validation pipeline.

    return failures

  def _get_test_plan(self, builds, snapshot):
    """Returns the test plan that should be executed for this invocation.

    Args:
      builds (list[build_pb2.Build]): builds to test.
      snapshot (GitilesCommit): Start ref of the child builds.
    """
    test_plan = self.m.cros_bisect.get_test_plan()
    if test_plan:
      return test_plan
    return self.m.cros_test_plan.generate(builds, snapshot.id)

  def _autotest_vm_test(self, build_target):
    """Returns the autotest builder name for the given build_target."""
    return build_target.name + '-autotest-vm'

  def _tast_vm_test(self, build_target):
    """Returns the tast builder name for the given build_target."""
    return build_target.name + '-tast-vm'

  def _schedule_skylab_tests(self, test_plan, passed_tests,
                             test_to_build_map=None, bb=False):
    """Schedule skylab tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
        be scheduled.
      passed_tests (list[string]): A list of names for the tests that
        have passed before.
      test_to_build_map (dict{string->string}): Map of test names to
        build_targets to be populated.
        bb(boolean): Whether to use buildbucket-backed cros_test_platform.
                      Note: this flag is temporary, and will exist only during
                      cros_test_platform migration.

    Returns:
      list[SkylabTask] of the tests scheduled.
    """
    skylab_tasks = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    with self.m.step.nest('schedule hardware tests'):
      for unit in test_plan.hw_test_units:
        for test in unit.hw_test_cfg.hw_test:
          if test.common.display_name not in passed_tests:
            test_name = test.common.display_name
            build_target = unit.common.build_target
            test_to_build_map[test_name] = build_target.name
            skylab_tasks.append(self.m.skylab.create_suite(test, unit, bb=bb))

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

  def _needs_baseline_validation(self, failed_results, test_plan,
                                 percent_threshold, count_threshold):
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
    test_count = sum(
        [len(unit.hw_test_cfg.hw_test) for unit in test_plan.hw_test_units] +
        [len(unit.vm_test_cfg.vm_test) for unit in test_plan.vm_test_units] + [
            len(unit.tast_vm_test_cfg.tast_vm_test)
            for unit in test_plan.tast_vm_test_units
        ])
    if failed_results:
      failure_ratio = float(len(failed_results)) / test_count
      if (failure_ratio <= float(percent_threshold) / 100 or
          len(failed_results) <= count_threshold):
        return True

    return False

  def _with_props_for_child_build(self, properties):
    """Merge 'properties' and 'api.cq.props_for_child_build'.

    Should be used to insert 'props_for_child_build' into properties being passed
    to a Buildbucket request.

    Args:
        api (RecipeApi): See RunSteps documentation.
        properties (dict): A dictionary of properties.

    Return:
        The merged dict.
    """
    properties.update(self.m.cq.props_for_child_build)
    return properties
