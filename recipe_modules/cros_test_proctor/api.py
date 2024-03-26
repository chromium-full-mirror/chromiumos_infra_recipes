# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for sending requests and processing results from cros test platform."""

from collections import defaultdict
from collections import OrderedDict
from typing import Dict, List

from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import StarlarkPackage
from RECIPE_MODULES.chromeos.cros_test_proctor import structs
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest
from google.protobuf import duration_pb2
from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.gce_test import GceTestProperties
from PB.recipes.chromeos.tast_vm import TastVmProperties
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.test_platform.steps.execution import ExecuteResponse
from recipe_engine import recipe_api

TEST_SUMMARY_KEY = 'test_summary'

# A Git footer that can be included in commit messages to tell the CQ run to
# enable an experiment.
CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'


class CrosTestProctorApi(recipe_api.RecipeApi):

  MetaTestTuple = structs.MetaTestTuple

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self.timeout = properties.timeout
    if not self.timeout.seconds:
      self.timeout = duration_pb2.Duration(seconds=9 * 60 * 60)
    self._vm_bucket = properties.vm_bucket or 'staging'
    self._skylab_task_per_build_target = properties.skylab_task_per_build_target
    self._test_summary = []
    self._not_runnable_addtnl_tests = []
    self._dry_run_exonerate_retried_suites = properties.dry_run_exonerate_retried_suites

    # Map from (host, project) combo to the local dir the repo was cloned to.
    # This is used to cache the results of _fetch_starlark_files().
    self._host_project_to_output_dir = {}

    # This is used to track the builders whose images are getting end-to-end
    # tested in this CQ run.
    self._builders_tested_in_this_run = set()

  @property
  def builders_tested_in_this_run(self):
    if self._test_data.get('builders_tested_in_this_run') is not None:
      return self._test_data.get('builders_tested_in_this_run')

    return self._builders_tested_in_this_run

  @property
  def test_summary(self):
    """Returns the test_summary for this build."""
    return self._test_summary

  @test_summary.setter
  def test_summary(self, test_summary):
    """Set the test_summary for this build.

    Args:
      test_summary (list[map{string: string}]): The test_summary for this build.
    """
    self._test_summary = test_summary
    self.m.easy.set_properties_step(**{TEST_SUMMARY_KEY: self._test_summary})

  def get_testable_builders(self, gerrit_changes: List[GerritChange],
                            builds: List[Build]) -> List[str]:
    """Returns the names of the builders whose images may be tested in this run.

    Uses the builds being considered by this CQ run and the relevant test plans
    based on the Gerrit Changes applied in order to determine which builders
    produce images that could be tested in this run.

    Args:
      gerrit_changes: Changes being tested in this CQ run.
      builds: The list of builds considered for this CQ run.

    Returns:
      The names of the builder whose images may be tested in this CQ run.
    """
    # The `testplan get-testable` command cannot be called with builds that are
    # missing build targets (e.g. chromite-cq).
    filtered_builds = [
        b for b in builds if 'build_target' in b.input.properties
    ]
    if not filtered_builds:
      return []
    relevant_plans = self.m.cros_test_plan_v2.relevant_plans(gerrit_changes)

    # At least one plan needs to be passed in when calling testplan.
    if not relevant_plans:
      return []

    starlark_files = self._fetch_starlark_files(relevant_plans)
    return self.m.cros_test_plan_v2.get_testable_builders(
        starlark_files, filtered_builds)

  def _fetch_starlark_files(self, source_test_plans):
    """Fetches a list of TestPlanStarlarkFiles to a local temp directory.

    Note that a given repo will only be cloned once. For example, if multiple
    TestPlanStarlarkFiles specify files in
    https://chromium.googlesource.com/platform/testrepoB, this repo will be
    cloned once, and then both returned StarlarkPackages will refer to the
    local path the repo was cloned to.

    Args:
      source_test_plans (list[SourceTestPlan]): A list of SourceTestPlans
        containing TestPlanStarlarkFiles to fetch.

    Returns:
      A list of StarlarkPackages for the fetched plans.
    """
    starlark_packages = []

    for plan in source_test_plans:
      for starlark_file in plan.test_plan_starlark_files:
        key = (starlark_file.host, starlark_file.project)

        # If the (host, project) combo has already been cloned, reuse the local
        # path it was cloned to. Otherwise, clone the repo and insert the local
        # path into the map.
        if key in self._host_project_to_output_dir:
          target_path = self._host_project_to_output_dir[key]
        else:
          output_dir = self.m.path.mkdtemp()
          target_path = self.m.path.join(output_dir, starlark_file.project)
          self.m.git.clone(
              'https://{}/{}'.format(starlark_file.host, starlark_file.project),
              target_path=target_path,
              single_branch=True,
              depth=1,
              verbose=True,
              progress=True,
          )

          self._host_project_to_output_dir[key] = target_path

        starlark_packages.append(
            StarlarkPackage(
                root=target_path,
                main=starlark_file.path,
                template_parameters=starlark_file.template_parameters,
            ),
        )

    return starlark_packages

  def run_proctor(self, need_tests_builds, snapshot, gerrit_changes,
                  enable_history, run_async=False, container_metadata=None,
                  require_stable_devices=False, use_test_plan_v2=False,
                  build_target_critical_allowlist=None):
    """Runs the test platform for a given bunch of builds.

    This is the entry point into the CrOS infra test platform via recipes.

    Args:
      need_tests_builds (list[build]): builds that are eligible for testing,
          i.e. ones that didn't suffer build failures.
      snapshot (common_pb2.GitilesCommit): the manifest snapshot at the time
          the included builds were created.
      gerrit_changes (list[common_pb2.GerritChange]): the changes that resulted
          in the provided builds, or None.
      enable_history (bool): whether to prune test history for previously
          successful tests on images with the same build inputs.
      run_async (bool): whether to stop and collect, if set we return no
          failures (an empty list).
      container_metadata (ContainerMetadata): Information on container
        images used for test execution.
      require_stable_devices (bool): whether to only run on devices with
        label-device-stable: True
      use_test_plan_v2 (bool): whether to use the v2 testplan tool in cros test
        platform v1 compatibility mode. The v2 testplan tool will return
        GenerateTestPlanResponse protos, so it is interchangable with the v1
        testplan tool.
      build_target_critical_allowlist: If set (including empty list), only the
        build targets specified can have tests run as critical. If None,
        criticality will not be modified for any build targets.
    Returns
      list[failures.Failure]: failures encountered running tests
    """
    with self.m.step.nest('run tests') as pres:
      # Filter Bazel builders.
      # TODO(b/330338112): Add test planning support for Bazel builders.
      need_tests_builds = [
          b for b in need_tests_builds
          if not self.m.cros_test_plan_v2.is_bazel_builder(b.builder.builder)
      ]

      if not need_tests_builds:
        pres.step_text = 'no builds to test'
        pres.properties['no_tests_needed'] = True
        return []

      with self.m.step.nest('schedule tests'):
        test_plan = self._get_test_plan(need_tests_builds, gerrit_changes,
                                        snapshot, use_test_plan_v2)

        # We will not run tests that have already passed for this patch set.
        previously_passed_tests = set()
        previously_failed_now_exonerable_hw_results = []
        previously_failed_now_exonerable_vm_builds = []
        is_retry = False
        if enable_history and gerrit_changes:
          is_retry = (self.m.cq.active and self.m.cros_history.is_retry)
          previously_passed_tests = self.m.cros_history.get_passed_tests()
          previously_failed_now_exonerable_vm_builds, previously_failed_now_exonerable_hw_results = self.m.exonerate.get_prev_failed_now_exonerable_test_results(
              test_plan, self._dry_run_exonerate_retried_suites)
        exonerable_vm_suites_names = {
            self.m.naming.get_vm_test_title(build)
            for build in previously_failed_now_exonerable_vm_builds
        }
        exonerable_hw_suites_names = {
            str(skylab_res.task.test.common.display_name)
            for skylab_res in previously_failed_now_exonerable_hw_results
        }

        test_tasks = self.schedule_tests(
            test_plan,
            previously_passed_tests,
            exonerable_hw_suites_names,
            exonerable_vm_suites_names,
            self.timeout,
            snapshot,
            is_retry=is_retry,
            run_async=run_async,
            container_metadata=container_metadata,
            require_stable_devices=require_stable_devices,
            build_target_critical_allowlist=build_target_critical_allowlist,
        )
      if run_async:
        return []

      with self.m.step.nest('collect tests'):
        test_results = self._collect_tests(test_tasks, timeout=self.timeout)
        # Record test results.
        passed_test_names = []
        passed_test_names.extend(exonerable_vm_suites_names)
        passed_test_names.extend(exonerable_hw_suites_names)
        crit_failure_test_names = []
        non_crit_failure_test_names = []
        for test_result in (test_results.tast_vm + test_results.skylab +
                            test_results.tast_gce):
          if test_result.status == common_pb2.SUCCESS:
            passed_test_names.append(self.m.naming.get_test_title(test_result))
          elif self.m.failures.is_critical_test_failure(test_result):
            crit_failure_test_names.append(
                self.m.naming.get_test_title(test_result))
          else:
            non_crit_failure_test_names.append(
                self.m.naming.get_test_title(test_result))

        self.test_summary = self._generate_test_summary(
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
      with self.m.step.nest('manual exoneration'):
        manually_exonerated_hw_results, manually_exonerated_hw_tests = (
            self.m.exonerate.exonerate_hwtests(test_results.skylab))
        passed_test_names += manually_exonerated_hw_tests
        manually_exonerated_vm_results, manually_exonerated_vm_tests = (
            self.m.exonerate.exonerate_vmtests(test_results.tast_vm))
        passed_test_names += manually_exonerated_vm_tests
        manually_exonerated_gce_results, manually_exonerated_gce_tests = (
            self.m.exonerate.exonerate_vmtests(test_results.tast_gce))
        passed_test_names += manually_exonerated_gce_tests
        self.m.exonerate.print_stats(property_name='exoneration_stats')

      with self.m.step.nest('automated exoneration') as pres:
        autoex_running = self.m.exonerate.auto_exoneration_analysis(
            fake_data=self._test_data.enabled)
        auto_exonerated_hw_results = manually_exonerated_hw_results
        auto_exonerated_vm_results = manually_exonerated_vm_results
        auto_exonerated_gce_results = manually_exonerated_gce_results
        if autoex_running:
          self.m.exonerate.enable_excludes()
          auto_exonerated_hw_results, auto_exonerated_hw_tests = (
              self.m.exonerate.exonerate_hwtests(manually_exonerated_hw_results)
          )
          passed_test_names += auto_exonerated_hw_tests
          auto_exonerated_vm_results, auto_exonerated_vm_tests = (
              self.m.exonerate.exonerate_vmtests(manually_exonerated_vm_results)
          )
          passed_test_names += auto_exonerated_vm_tests
          auto_exonerated_gce_results, auto_exonerated_gce_tests = (
              self.m.exonerate.exonerate_vmtests(
                  manually_exonerated_gce_results))
          passed_test_names += auto_exonerated_gce_tests
          self.m.exonerate.print_stats(property_name='autoex_stats')

      test_results = test_results._replace(
          skylab=auto_exonerated_hw_results +
          previously_failed_now_exonerable_hw_results)
      test_results = test_results._replace(
          tast_vm=auto_exonerated_vm_results +
          previously_failed_now_exonerable_vm_builds)
      test_results = test_results._replace(tast_gce=auto_exonerated_gce_results)
      self.m.exonerate.populate_exoneration_markdown()

      with self.m.step.nest('fault attribution'):
        self.m.cq_fault_attribution.set_cq_fault_attribute_properties(
            test_results, snapshot)

      self.m.cros_history.set_passed_tests(passed_test_names)
      self.m.greenness.update_vmtest_info(test_results.tast_vm)
      self.m.greenness.update_vmtest_info(test_results.tast_gce)
      failures = self.get_test_failures(test_results)
      failures += self.m.failures.get_additional_hw_test_not_run_failures(
          self._not_runnable_addtnl_tests)
    return failures

  def _get_test_plan(self, builds, gerrit_changes, snapshot, use_test_plan_v2):
    """Returns the test plan that should be executed for this invocation.

    Args:
      builds (list[build_pb2.Build]): builds to test.
      gerrit_changes (list[common_pb2.GerritChange]): the changes that resulted
          in the provided builds, or None.
      snapshot (GitilesCommit): Start ref of the child builds.
      use_test_plan_v2 (bool): whether to use the v2 testplan tool in cros test
        platform v1 compatibility mode. The v2 testplan tool will return
        GenerateTestPlanResponse protos, so it is interchangable with the v1
        testplan tool.

    Returns:
      GenerateTestPlanResponse: the test plan.
    """
    if use_test_plan_v2:
      relevant_plans = self.m.cros_test_plan_v2.relevant_plans(gerrit_changes)

      starlark_files = self._fetch_starlark_files(relevant_plans)

      req = GenerateTestPlanRequest(buildbucket_protos=[
          ProtoBytes(
              serialized_proto=build.SerializeToString(deterministic=True))
          for build in builds
      ])
      test_plan = self.m.cros_test_plan_v2.generate_hw_test_plans(
          starlark_files, generate_test_plan_request=req
      ) if starlark_files else GenerateTestPlanResponse()
    else:
      test_plan = self.m.cros_test_plan.generate(builds, gerrit_changes,
                                                 snapshot)
    try:
      self.m.cros_cq_additional_tests.append_user_provided_test_suites_to_test_plan(
          builds, gerrit_changes, test_plan)
    except self.m.cros_cq_additional_tests.CrosCqAddnlTestsMissingBuildTargetsError as e:
      self._not_runnable_addtnl_tests = e.not_runnable_addtnl_tests

    return test_plan

  def _tast_vm_builder(self, build_target, expressions):
    """Returns the tast builder name for the given build_target and expressions."""
    staging_prefix = 'staging-' if self.m.cros_infra_config.is_staging else ''
    if '!informational' in ''.join(
        expressions) or '!"informational"' in ''.join(expressions):
      return staging_prefix + build_target.name + '-direct-tast-vm'
    return staging_prefix + build_target.name + '-tast-vm-informational'

  def _tast_gce_builder(self, build_target, expressions):
    """Returns the GCE builder name for the given build_target and expressions."""
    staging_prefix = 'staging-' if self.m.cros_infra_config.is_staging else ''
    if '!informational' in ''.join(
        expressions) or '!"informational"' in ''.join(expressions):
      return staging_prefix + build_target.name + '-tast-gce'
    return staging_prefix + build_target.name + '-tast-gce-informational'

  def schedule_tests(self, test_plan, passed_tests,
                     previously_failed_now_exonerable_hw_suites,
                     previously_failed_now_exonerable_vm_suites, timeout,
                     snapshot=None, is_retry=False, run_async=False,
                     container_metadata=None, require_stable_devices=False,
                     build_target_critical_allowlist=None):
    """Schedule all tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      previously_failed_now_exonerable_hw_suites (list[string]): Previously
          failed tests that are now eligible for exoneration.
      previously_failed_now_exonerable_vm_suites (list[string]): Previously
          failed tests that are now eligible for exoneration.
      timeout (Duration): Timeout in duration_pb2.Duration.
      snapshot (common_pb2.GitilesCommit): the manifest snapshot at the time
          the included builds were created.
      is_retry (bool): Whether this is a CQ retry.
      run_async (bool): whether to stop and collect, if set we return no
          failures (an empty list).
      container_metadata (ContainerMetadata): Information on container
        images used for test execution.
      require_stable_devices (bool): whether to only run on devices with
        label-device-stable: True
      build_target_critical_allowlist: If set (including empty list), only the
        build targets specified can have tests run as critical. If None,
        criticality will not be modified for any build targets.

    Returns:
      MetaTestTuple of lists of the tests scheduled.
    """

    def _persist_task_ids_in_properties(test_tasks: structs.MetaTestTuple):
      skylab_ids = sorted(
          {str(skylab_task.id) for skylab_task in test_tasks.skylab})
      vm_tests_build_ids = sorted({str(test.id) for test in test_tasks.tast_vm})
      self.m.easy.set_properties_step(
          test_tasks={
              'skylab_builder_ids': skylab_ids,
              'tast_vm_tests_builder_ids': vm_tests_build_ids,
          })

    skylab_tasks = self._schedule_skylab_tests(
        test_plan,
        passed_tests,
        previously_failed_now_exonerable_hw_suites,
        timeout,
        is_retry,
        run_async=run_async,
        container_metadata=container_metadata,
        require_stable_devices=require_stable_devices,
        task_per_build_target=self._skylab_task_per_build_target,
        build_target_critical_allowlist=build_target_critical_allowlist,
    )
    tast_vm_tests = self._schedule_tast_vm_tests(
        test_plan, passed_tests, previously_failed_now_exonerable_vm_suites,
        snapshot, is_retry, run_async=run_async)

    tast_gce_tests = self._schedule_tast_gce_tests(test_plan, passed_tests,
                                                   snapshot, is_retry,
                                                   run_async=run_async)

    self.m.easy.set_properties_step()
    tests_tasks = self.MetaTestTuple(skylab=skylab_tasks or [], autotest_vm=[],
                                     tast_vm=tast_vm_tests or [],
                                     tast_gce=tast_gce_tests or [])
    _persist_task_ids_in_properties(tests_tasks)
    return tests_tasks

  def _collect_tests(self, test_tasks, timeout):
    """Collect on all tests from test_tasks.

    The tests are collected in the order: skylab,
    tast_vm, tast_gce.

    Args:
      test_tasks (MetaTestTuple): lists of tests to collect.
      timeout (Duration): Timeout in duration_pb2.Duration.

    Returns:
      MetaTestTuple of lists of tests collected.
    """

    def collect_vm_tests(build_ids, vm_test_type, timeout):
      timeout = int(timeout.seconds)
      try:
        step_name = 'collect %s tests' % vm_test_type
        return list(
            self.m.buildbucket.collect_builds(build_ids, step_name=step_name,
                                              timeout=timeout).values())
      except recipe_api.StepFailure:
        step_name = 'get %s tests' % vm_test_type
        return list(
            self.m.buildbucket.get_multi(build_ids,
                                         step_name=step_name).values())

    results = OrderedDict({
        'skylab': [],
        'autotest_vm': [],
        'tast_vm': [],
        'tast_gce': []
    })

    def update_results(key, resp):
      results[key] = resp

    runner = self.m.future_utils.create_parallel_runner()
    # Collect hw test results.
    runner.run_function_async(
        lambda _, _2: self.m.skylab.wait_on_suites(test_tasks.skylab, timeout),
        None, success_handler=lambda resp: update_results('skylab', resp))
    # Collect tast vm test results.
    runner.run_function_async(
        lambda _, _2: collect_vm_tests([vt.id for vt in test_tasks.tast_vm],
                                       'tast vm', timeout), None,
        success_handler=lambda resp: update_results('tast_vm', resp))
    # Collect tast GCE test results.
    runner.run_function_async(
        lambda _, _2: collect_vm_tests([vt.id for vt in test_tasks.tast_gce],
                                       'tast GCE', timeout), None,
        success_handler=lambda resp: update_results('tast_gce', resp))

    runner.wait_for_and_get_responses()
    return self.MetaTestTuple(**results)

  def get_test_failures(self, test_results):
    """Logs all test failures to the UI and raises on failed tests.

    Args:
      test_results: MetaTestTuple of the tests on the changes.
    Returns:
      list[Failure]: All failures discovered in the given run.
    """
    failures = self.m.failures.get_hw_test_results(test_results.skylab).failures
    failures += self.m.failures.get_vm_test_results(
        test_results.tast_vm).failures
    failures += self.m.failures.get_vm_test_results(
        test_results.tast_gce).failures
    return failures

  def _schedule_skylab_tests(
      self, test_plan, passed_tests, previously_failed_now_exonerable_hw_suites,
      timeout, is_retry=False, run_async=False, container_metadata=None,
      require_stable_devices=False, task_per_build_target=False,
      build_target_critical_allowlist=None):
    """Schedule skylab tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      previously_failed_now_exonerable_hw_suites (list[string]): Previously
          failed tests that are now eligible for exoneration.
      timeout (Duration): Timeout in duration_pb2.Duration.
      is_retry (bool): Whether this is a CQ retry.
      run_async (bool): Should the tests be ran async and not cancel
          on the termination of the parent (this caller).
      container_metadata (ContainerMetadata): Information on container
          images used for test execution.
      require_stable_devices (bool): Whether to only run on devices with
          label-device-stable: True
      task_per_build_target (bool): Should we schedule a unique invocation
          of cros_test_platform per build target.
      build_target_critical_allowlist: If set (including empty list), only the
        build targets specified can have tests run as critical. If None,
        criticality will not be modified for any build targets.

    Returns:
      list[SkylabTask] of the tests scheduled.
    """

    def _is_skippable(test):
      return (
          test.common.display_name in passed_tests or
          test.common.display_name in previously_failed_now_exonerable_hw_suites
      )

    skylab_tasks = []
    # Record the names of all the tests that are scheduled. This will be set as
    # an output property when testing Recipes only.
    scheduled_test_names = []

    with self.m.step.nest('schedule hardware tests'):
      # A map from {build_target_name: [test_name]}.
      tests_to_run = defaultdict(list)
      hw_build_targets = set()
      # pylint: disable=unused-variable
      previous_test_results = self._previous_test_results()
      for unit in test_plan.hw_test_units:
        for test in unit.hw_test_cfg.hw_test:
          # Do not run non-critical tests on retries.
          if is_retry and not test.common.critical.value:
            continue
          if not _is_skippable(test):
            build_target = unit.common.build_target
            tests_to_run[build_target.name].append(
                UnitHwTest(unit=unit, hw_test=test))
            hw_build_targets.add(build_target.name)

            # Record information about what is getting tested.
            self._builders_tested_in_this_run.add(unit.common.builder_name)
            scheduled_test_names.append(test.common.display_name)

      _ALL_BUILD_TARGETS = 'all build targets'
      if tests_to_run:
        # If we aren't scheduling per build_target, flatten into one invocation.
        if not task_per_build_target:
          tests_to_run = {_ALL_BUILD_TARGETS: sum(tests_to_run.values(), [])}
        for test_build_target, bt_tests_to_run in sorted(tests_to_run.items()):
          skylab_tasks.extend(
              self.m.skylab.schedule_suites(
                  bt_tests_to_run,
                  timeout,
                  async_suite_run=run_async,
                  container_metadata=container_metadata,
                  require_stable_devices=require_stable_devices,
                  name=None if test_build_target == _ALL_BUILD_TARGETS else
                  test_build_target,
                  previous_results=previous_test_results,
                  build_target_critical_allowlist=build_target_critical_allowlist,
              ))
      self.m.easy.set_properties_step(
          hw_test_build_targets=len(hw_build_targets))
      self.m.easy.set_properties_step(
          hw_test_suites=len(sum(tests_to_run.values(), [])))
      if self._test_data.enabled:
        scheduled_test_names.sort()
        self.m.easy.set_properties_step(scheduled_hw_tests=scheduled_test_names)
    return skylab_tasks

  def _schedule_tast_vm_tests(self, test_plan, passed_tests,
                              previously_failed_now_exonerable_vm_suites,
                              snapshot, is_retry=False, run_async=False):
    """Schedule tast VM Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      previously_failed_now_exonerable_vm_suites (list[string]):
          Previously failed tests that are now eligible for exoneration.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      is_retry (bool): Whether this is a CQ retry.
      run_async (bool): Should the tests be ran async and not cancel
          on the termination of the parent (this caller).

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []

    exps = self.m.cros_infra_config.experiments_for_child_build
    footer_exps = self.m.git_footers.get_footer_values(
        self.m.src_state.gerrit_changes, CROS_EXPERIMENTS_FOOTER,
        step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
    exps.update({x: True for x in footer_exps})

    tags = self.m.cros_tags.make_schedule_tags(snapshot)
    tags.extend(self.m.cros_tags.tags(**{'hide-in-gerrit': 'true'}))

    # Record the names of all the tests that are scheduled. This will be set as
    # an output property when testing Recipes only.
    scheduled_test_names = []

    for unit in test_plan.direct_tast_vm_test_units:
      for test in unit.tast_vm_test_cfg.tast_vm_test:
        # Do not run non-critical tests on retries.
        if is_retry and not test.common.critical.value:
          continue
        if (test.common.display_name not in passed_tests and
            test.common.display_name not in
            previously_failed_now_exonerable_vm_suites):
          test_name = test.common.display_name
          build_target = unit.common.build_target
          expressions = [t.test_expr for t in test.tast_test_expr]
          total_shards = test.tast_test_shard.total_shards
          shard_index = test.tast_test_shard.shard_index
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot,
                  builder=self._tast_vm_builder(build_target, expressions),
                  bucket=self._vm_bucket, critical=test.common.critical.value,
                  experiments=exps, properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TastVmProperties(
                              name=test_name, build_target=build_target,
                              build_payload=unit.common.build_payload,
                              expressions=expressions,
                              total_shards=total_shards,
                              shard_index=shard_index))), tags=tags,
                  swarming_parent_run_id=None if run_async else
                  self.m.swarming.task_id, can_outlive_parent=run_async))

          # Record information about what is getting tested.
          self._builders_tested_in_this_run.add(unit.common.builder_name)
          scheduled_test_names.append(test.common.display_name)

    vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule tast vm tests',
        url_title_fn=self.m.naming.get_vm_test_title)
    if self._test_data.enabled:
      scheduled_test_names.sort()
      self.m.easy.set_properties_step(
          scheduled_tast_vm_tests=scheduled_test_names)
    return vm_tests

  def _schedule_tast_gce_tests(self, test_plan, passed_tests, snapshot,
                               is_retry=False, run_async=False):
    """Schedule tast GCE Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      is_retry (bool): Whether this is a CQ retry.
      run_async (bool): Should the tests be ran async and not cancel
          on the termination of the parent (this caller).

    Returns:
      list[Build] objects of the GCE tests scheduled.
    """
    requests = []

    # Record the names of all the tests that are scheduled. This will be set as
    # an output property when testing Recipes only.
    scheduled_test_names = []

    exps = self.m.cros_infra_config.experiments_for_child_build
    footer_exps = self.m.git_footers.get_footer_values(
        self.m.src_state.gerrit_changes, CROS_EXPERIMENTS_FOOTER,
        step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
    exps.update({x: True for x in footer_exps})

    tags = self.m.cros_tags.make_schedule_tags(snapshot)
    tags.extend(self.m.cros_tags.tags(**{'hide-in-gerrit': 'true'}))

    for unit in test_plan.tast_gce_test_units:
      for test in unit.tast_gce_test_cfg.tast_gce_test:
        # Do not run non-critical tests on retries.
        if is_retry and not test.common.critical.value:
          continue
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          expressions = [t.test_expr for t in test.tast_test_expr]
          total_shards = test.tast_test_shard.total_shards
          shard_index = test.tast_test_shard.shard_index
          gce_metadata = test.gce_metadata
          properties_gce_metadata = GceTestProperties.GceMetadata(
              project=gce_metadata.project,
              zone=gce_metadata.zone,
              machine_type=gce_metadata.machine_type,
              network=gce_metadata.network,
              subnet=gce_metadata.subnet,
          )
          requests.append(
              self.m.buildbucket.schedule_request(
                  gitiles_commit=snapshot,
                  builder=self._tast_gce_builder(build_target, expressions),
                  bucket=self._vm_bucket, critical=test.common.critical.value,
                  experiments=exps, properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          GceTestProperties(
                              name=test_name, build_target=build_target,
                              build_payload=unit.common.build_payload,
                              expressions=expressions,
                              total_shards=total_shards,
                              shard_index=shard_index,
                              gce_metadata=properties_gce_metadata))),
                  tags=tags, swarming_parent_run_id=None if run_async else
                  self.m.swarming.task_id, can_outlive_parent=run_async))

          # Record information about what is getting tested.
          self._builders_tested_in_this_run.add(unit.common.builder_name)
          scheduled_test_names.append(test.common.display_name)

    gce_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule tast GCE tests',
        url_title_fn=self.m.naming.get_vm_test_title)
    if self._test_data.enabled:
      scheduled_test_names.sort()
      self.m.easy.set_properties_step(
          scheduled_tast_gce_tests=scheduled_test_names)
    return gce_tests

  def _generate_test_summary(self, test_plan, passed_test_names):
    """Creates a summary of the test results.

    Args:
      test_plan (GenerateTestPlanResponse): The test plan.
      passed_test_names (list[str]): The names of the passed tests.

    Returns:
      test_summary (list[dict]):  A summary of tests, one item per test
        detailing display name, criticality, and last status.
    """
    # Use cases:
    # * CQ test and build planning.
    # * Assist analysis of test results by dashboards with access to the
    #   buildbucket tables.
    test_summary = (
        self._extract_test_summary(test_plan.hw_test_units, lambda unit: unit.
                                   hw_test_cfg, lambda cfg: cfg.hw_test,
                                   passed_test_names) +
        self._extract_test_summary(
            test_plan.direct_tast_vm_test_units, lambda unit: unit.
            tast_vm_test_cfg, lambda cfg: cfg.tast_vm_test, passed_test_names) +
        self._extract_test_summary(
            test_plan.tast_gce_test_units, lambda unit: unit.tast_gce_test_cfg,
            lambda cfg: cfg.tast_gce_test, passed_test_names))
    return test_summary

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
      build_target = unit.common.build_target.name
      builder_name = unit.common.builder_name
      for test in tests_func(cfg_func(unit)):
        name = test.common.display_name
        status = 'SUCCESS' if name in passed_test_names else 'FAILURE'
        critical = test.common.critical and test.common.critical.value
        board = test.skylab_board if isinstance(test,
                                                HwTestCfg.HwTest) else None
        model = test.skylab_model if isinstance(test,
                                                HwTestCfg.HwTest) else None
        # This is extensible to other fields beyond criticality if needed in
        # future (did the test pass previously, did it pass this time, etc.).
        result.append({
            'name': name,
            'board': board,
            'model': model,
            'builder_name': builder_name,
            'build_target': build_target,
            'critical': critical,
            'status': status,
        })
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

  def _previous_test_results(self) -> Dict[str, ExecuteResponse]:
    """Gets the test results from the latest test invocation.

    Currently only returns HW test results.
    TODO(b/271938042): Also return VM test results.

    Returns:
      The ExecuteResponses.tagged_response from the latest invocation.
    """
    previous_test_results = {}
    if not self.m.cq.active:
      return previous_test_results

    with self.m.step.nest('get previous test results') as presentation:
      _, test_task_ids = self.m.cros_history.get_previous_test_task_ids()
      # CQ only launches one cros_test_platform builder.
      if len(test_task_ids) == 1:
        build = self.m.buildbucket.get(test_task_ids[0])
        previous_test_results = self.m.skylab_results.get_tagged_execute_responses_from_build(
            build)
        for name, results in previous_test_results.items():
          presentation.logs[name] = json_format.MessageToJson(results)

    return previous_test_results
