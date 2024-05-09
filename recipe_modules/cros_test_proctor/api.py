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
      need_tests_builds (list[Build]): builds that are eligible for testing,
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
        is_retry = False
        if enable_history and gerrit_changes:
          is_retry = (self.m.cv.active and self.m.cros_history.is_retry)
          previously_passed_tests = self.m.cros_history.get_passed_tests()
          previously_failed_now_exonerable_hw_results = self.m.exonerate.get_prev_failed_now_exonerable_test_results(
              test_plan, self._dry_run_exonerate_retried_suites)
        exonerable_hw_suites_names = {
            str(skylab_res.task.test.common.display_name)
            for skylab_res in previously_failed_now_exonerable_hw_results
        }

        test_tasks = self.schedule_tests(
            test_plan,
            previously_passed_tests,
            exonerable_hw_suites_names,
            self.timeout,
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
        passed_test_names.extend(exonerable_hw_suites_names)
        crit_failure_test_names = []
        non_crit_failure_test_names = []
        for test_result in test_results.skylab:
          if test_result.status == common_pb2.SUCCESS:
            passed_test_names.append(self.m.naming.get_test_title(test_result))
          elif self.m.failures.is_critical_test_failure(test_result):
            crit_failure_test_names.append(
                self.m.naming.get_test_title(test_result))
          else:
            non_crit_failure_test_names.append(
                self.m.naming.get_test_title(test_result))

        self.test_summary = self._generate_test_summary(
            test_plan, previously_passed_tests.union(set(passed_test_names)),
            need_tests_builds)

      if crit_failure_test_names:
        pres.step_text = ('{} critical test(s) failed'.format(
            len(crit_failure_test_names)))
      elif passed_test_names:
        pres.step_text = ('all critical tests passed.')
      else:  #pragma: no cover
        # This shouldn't ever happen with multi-request
        pres.step_text = ('no tests were necessary')
        pres.properties['no_tests_needed'] = True

    with self.m.step.nest('check test results') as pres:
      # Output a link to the CTP build. Some orchestrators (ie postsubmit)
      # schedule multiple CTP builds; do not output a link in this case.
      if not self._skylab_task_per_build_target and len(
          test_results.skylab) > 0:
        pres.links[
            'cros_test_platform build'] = self.m.urls.get_skylab_task_url(
                test_results.skylab[0].task)
      with self.m.step.nest('manual exoneration'):
        manually_exonerated_hw_results, manually_exonerated_hw_tests = (
            self.m.exonerate.exonerate_hwtests(test_results.skylab))
        passed_test_names += manually_exonerated_hw_tests
        self.m.exonerate.print_stats(property_name='exoneration_stats')

      with self.m.step.nest('automated exoneration') as pres:
        autoex_running = self.m.exonerate.auto_exoneration_analysis(
            fake_data=self._test_data.enabled)
        auto_exonerated_hw_results = manually_exonerated_hw_results
        if autoex_running:
          self.m.exonerate.enable_excludes()
          auto_exonerated_hw_results, auto_exonerated_hw_tests = (
              self.m.exonerate.exonerate_hwtests(manually_exonerated_hw_results)
          )
          passed_test_names += auto_exonerated_hw_tests
          self.m.exonerate.print_stats(property_name='autoex_stats')

      test_results = test_results._replace(
          skylab=auto_exonerated_hw_results +
          previously_failed_now_exonerable_hw_results)
      self.m.exonerate.populate_exoneration_markdown()

      with self.m.step.nest('fault attribution'):
        self.m.cq_fault_attribution.set_cq_fault_attribute_properties(
            test_results, snapshot)

      self.m.cros_history.set_passed_tests(passed_test_names)
      self.m.greenness.update_hwtest_info(test_results.skylab)
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

  def schedule_tests(self, test_plan, passed_tests,
                     previously_failed_now_exonerable_hw_suites, timeout,
                     is_retry=False, run_async=False, container_metadata=None,
                     require_stable_devices=False,
                     build_target_critical_allowlist=None):
    """Schedule all tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      previously_failed_now_exonerable_hw_suites (list[string]): Previously
          failed tests that are now eligible for exoneration.
      timeout (Duration): Timeout in duration_pb2.Duration.
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
      self.m.easy.set_properties_step(test_tasks={
          'skylab_builder_ids': skylab_ids,
          'tast_vm_tests_builder_ids': [],
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
    self.m.easy.set_properties_step()
    tests_tasks = self.MetaTestTuple(skylab=skylab_tasks or [], autotest_vm=[],
                                     tast_vm=[], tast_gce=[])
    _persist_task_ids_in_properties(tests_tasks)
    return tests_tasks

  def _collect_tests(self, test_tasks, timeout):
    """Collect on all tests from test_tasks.

    Args:
      test_tasks (MetaTestTuple): lists of tests to collect.
      timeout (Duration): Timeout in duration_pb2.Duration.

    Returns:
      MetaTestTuple of lists of tests collected.
    """
    results = OrderedDict({
        'skylab': [],
        'autotest_vm': [],
        'tast_vm': [],
        'tast_gce': []
    })

    def update_results(key, resp):
      results[key] = resp

    # TODO(b/315338399): Cleanup parallel collection as we don't need it anymore.
    runner = self.m.future_utils.create_parallel_runner()
    # Collect hw test results.
    runner.run_function_async(
        lambda _, _2: self.m.skylab.wait_on_suites(test_tasks.skylab, timeout),
        None, success_handler=lambda resp: update_results('skylab', resp))

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

  def _generate_test_summary(self, test_plan, passed_test_names, test_builds):
    """Creates a summary of the test results.

    Args:
      test_plan (GenerateTestPlanResponse): The test plan.
      passed_test_names (list[str]): The names of the passed tests.
      test_builds (list[Build]): Builds that are eligible for testing.

    Returns:
      test_summary (list[dict]):  A summary of tests, one item per test
        detailing display name, criticality, and last status.
    """
    # Use cases:
    # * CQ test and build planning.
    # * Assist analysis of test results by dashboards with access to the
    #   buildbucket tables.
    test_summary = (
        self._extract_test_summary(test_plan.hw_test_units,
                                   lambda unit: unit.hw_test_cfg,
                                   lambda cfg: cfg.hw_test, passed_test_names,
                                   test_builds))
    return test_summary

  def _extract_test_summary(self, units, cfg_func, tests_func,
                            passed_test_names, test_builds):
    """Returns a summary of the tests within `units`.

    Args:
      units (list[HwTestUnit]): Units to count the
          critical tests within.
      cfg_func (lambda): Lambda function that takes a unit from units and
          returns the *test_cfg field.
      tests_func (lambda): Lambda function that takes the *test_cfg field and
          returns the *test field holding the list of tests.
      passed_test_names (list[str]): The names of the passed tests.
      test_builds (list[Build]): Builds that are eligible for testing.

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
            'name':
                name,
            'board':
                board,
            'model':
                model,
            'builder_name':
                builder_name,
            'build_target':
                build_target,
            'critical':
                critical,
            'status':
                status,
            'revision':
                self._get_revision_for_builder(builder_name, test_builds),
        })
    return result

  def _get_revision_for_builder(self, builder_name, test_builds):
    """Gets the gitiles commit of the build used for testing.

    Args:
      builder_name (str): Name of the builder.
      test_builds (list[Build]): Builds that are eligible for testing.

    Returns:
      str: The gitiles commit if found, otherwise, empty string.
    """
    for build in test_builds:
      if build.builder.builder == builder_name:
        return build.input.gitiles_commit.id
    return ''

  def _previous_test_results(self) -> Dict[str, ExecuteResponse]:
    """Gets the test results from the latest test invocation.

    Returns:
      The ExecuteResponses.tagged_response from the latest invocation.
    """
    previous_test_results = {}
    if not self.m.cv.active:
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
