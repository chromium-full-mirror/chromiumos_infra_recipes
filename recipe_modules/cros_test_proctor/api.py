# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import defaultdict
import json

from google.protobuf import json_format
from google.protobuf import duration_pb2

from recipe_engine import recipe_api

from RECIPE_MODULES.chromeos.cros_test_proctor import structs

from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.gce_test import GceTestProperties
from PB.recipes.chromeos.tast_vm import TastVmProperties
from PB.testplans.generate_test_plan import GenerateTestPlanRequest, GenerateTestPlanResponse

TEST_SUMMARY_KEY = 'test_summary'
SNAPSHOT_HWTEST_SUITES = [
    'bvt-tast-cq', 'bvt-arc', 'bvt-tast-arc', 'bvt-inline'
]

# A Git footer that can be included in commit messages to tell the CQ run to
# enable an experiment.
CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'


class CrosTestProctorApi(recipe_api.RecipeApi):

  MetaTestTuple = structs.MetaTestTuple

  def __init__(self, properties, **kwargs):
    super(CrosTestProctorApi, self).__init__(**kwargs)
    self.timeout = properties.timeout
    if not self.timeout.seconds:
      self.timeout = duration_pb2.Duration(seconds=9 * 60 * 60)
    self._vm_bucket = properties.vm_bucket or "staging"
    self._skylab_task_per_build_target = properties.skylab_task_per_build_target
    self._test_summary = []
    self._not_runnable_addtnl_tests = []

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

    # Map from (host, project) combo to the local dir the repo was cloned to.
    # This is used to prevent cloning the same repo twice.
    host_project_to_output_dir = {}

    for plan in source_test_plans:
      for starlark_file in plan.test_plan_starlark_files:
        key = (starlark_file.host, starlark_file.project)

        # If the (host, project) combo has already been cloned, reuse the local
        # path it was cloned to. Otherwise, clone the repo and insert the local
        # path into the map.
        if key in host_project_to_output_dir:
          target_path = host_project_to_output_dir[key]
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

          host_project_to_output_dir[key] = target_path

        starlark_packages.append(
            self.m.cros_test_plan_v2.StarlarkPackage(
                root=target_path,
                main=starlark_file.path,
            ),
        )

    return starlark_packages

  def run_proctor_v2(self, gerrit_changes):
    """Runs the test platform v2 for a set of GerritChanges.

    Args:
      gerrit_changes (list[common_pb2.GerritChange]): changes to test.
    """
    with self.m.step.nest('run tests') as pres:
      with self.m.step.nest('schedule tests'):
        relevant_plans = self.m.cros_test_plan_v2.relevant_plans(gerrit_changes)

        starlark_files = self._fetch_starlark_files(relevant_plans)

        if starlark_files:
          hw_test_plans = self.m.cros_test_plan_v2.generate_hw_test_plans(
              starlark_files)

          # TODO(b/217973414): Replace with MessageToJson once we don't need to
          # fix the separator spacing between py2 and py3 MessageToJson.
          pres.logs['hw_test_plans'] = '\n'.join(
              json.dumps(
                  json_format.MessageToDict(p), separators=(
                      ',', ':'), sort_keys=True, indent=2)
              for p in hw_test_plans)
        else:
          pres.step_text = 'No starlark files found.'

        # TODO(b/182898188): Call CTP2 when it is available.
        raise ValueError('CTP2 not implemented')

  def run_proctor(self, need_tests_builds, snapshot, gerrit_changes,
                  enable_history, run_async=False, container_metadata=None,
                  require_stable_devices=False, use_test_plan_v2=False):
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
    Returns
      list[failures.Failure]: failures encountered running tests
    """
    with self.m.step.nest('run tests') as pres:
      with self.m.step.nest('schedule tests'):
        test_plan = self._get_test_plan(need_tests_builds, gerrit_changes,
                                        snapshot, use_test_plan_v2)

        # We will not run tests that have already passed for this patch set.
        previously_passed_tests = set()
        is_retry = False
        if enable_history and gerrit_changes:
          is_retry = (self.m.cq.active and self.m.cros_history.is_retry())
          previously_passed_tests = self.m.cros_history.get_passed_tests()

        test_to_build_target_map = {}
        test_tasks = self.schedule_tests(
            test_plan,
            previously_passed_tests,
            self.timeout,
            test_to_build_target_map,
            snapshot,
            is_retry=is_retry,
            run_async=run_async,
            container_metadata=container_metadata,
            require_stable_devices=require_stable_devices,
        )
      if run_async:
        return []

      with self.m.step.nest('collect tests'):
        test_results = self._collect_tests(test_tasks, timeout=self.timeout)
        # Record test results.
        passed_test_names = []
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
      exonerated_hw_results, exonerated_hw_tests = self.m.exonerate.exonerate_hwtests(
          test_results.skylab)
      passed_test_names += exonerated_hw_tests
      test_results = test_results._replace(skylab=exonerated_hw_results)
      exonerated_vm_results, exonerated_vm_tests = self.m.exonerate.exonerate_vmtests(
          test_results.tast_vm)
      passed_test_names += exonerated_vm_tests
      test_results = test_results._replace(tast_vm=exonerated_vm_results)
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
    test_plan = self.m.cros_bisect.get_test_plan(builds)
    if test_plan:
      return test_plan

    if use_test_plan_v2:
      relevant_plans = self.m.cros_test_plan_v2.relevant_plans(gerrit_changes)

      starlark_files = self._fetch_starlark_files(relevant_plans)

      # TODO(b/217973414): No need to ensure deterministic ordering once we no
      # longer need to ensure parity between PY2 and PY3.
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
    if '!informational' in ''.join(expressions):
      return staging_prefix + build_target.name + '-direct-tast-vm'
    else:
      return staging_prefix + build_target.name + '-tast-vm-informational'

  def _tast_gce_builder(self, build_target, expressions):
    """Returns the GCE builder name for the given build_target and expressions."""
    if '!informational' in ''.join(expressions):
      return build_target.name + '-tast-gce'
    else:
      return build_target.name + '-tast-gce-informational'

  def _get_non_informational(self, tast_unit):
    test_cfg = tast_unit.tast_vm_test_cfg
    tast_unit.tast_vm_test_cfg.ClearField('tast_vm_test')
    filtered_tests = [
        test for test in test_cfg.tast_vm_test
        if 'informational' not in test.suite_name
    ]
    tast_unit.tast_vm_test_cfg.tast_vm_test.extend(filtered_tests)
    return tast_unit

  def _filter_tast_gce_informational(self, tast_gce_unit):
    """Modifies test plan unit to not include informational tests."""
    test_cfg = tast_gce_unit.tast_gce_test_cfg
    tast_gce_unit.tast_gce_test_cfg.ClearField('tast_gce_test')
    filtered_tests = [
        test for test in test_cfg.tast_gce_test
        if 'informational' not in test.suite_name
    ]
    tast_gce_unit.tast_gce_test_cfg.tast_gce_test.extend(filtered_tests)
    return tast_gce_unit

  def _filter_snapshot_hw_test_units(self, hw_test_units):
    """Restrict to SNAPSHOT_HWTEST_SUITES only."""
    filtered_hw_test_units = []
    for test_unit in hw_test_units:
      filtered_hw_test = []
      for hw_test in test_unit.hw_test_cfg.hw_test:
        if hw_test.suite in SNAPSHOT_HWTEST_SUITES:
          filtered_hw_test.append(hw_test)

      if filtered_hw_test:
        filtered_hw_test_units.append(
            HwTestUnit(common=test_unit.common,
                       hw_test_cfg=HwTestCfg(hw_test=filtered_hw_test)))

    return filtered_hw_test_units

  def _filter_snapshot_test_plan(self, test_plan):
    """Filter tests out of test_plan selectively.

    Args:
      test_plan (GenerateTestPlanResponse): Test plan for the input builds.

    Returns:
      GenerateTestPlanResponse of tests that should run.
    """
    # Remove informational tast VM tests from test_plan.
    if self.m.buildbucket.build.builder.builder == "snapshot-orchestrator":
      with self.m.step.nest('filter test plan') as pres:
        non_informational_units = [
            self._get_non_informational(unit)
            for unit in test_plan.direct_tast_vm_test_units
        ]
        non_informational_gce_units = [
            self._filter_tast_gce_informational(unit)
            for unit in test_plan.tast_gce_test_units
        ]
        filtered_hw_test_units = self._filter_snapshot_hw_test_units(
            test_plan.hw_test_units)

        test_plan.ClearField("direct_tast_vm_test_units")
        test_plan.ClearField('tast_gce_test_units')
        test_plan.ClearField("hw_test_units")

        test_plan.direct_tast_vm_test_units.extend(non_informational_units)
        test_plan.tast_gce_test_units.extend(non_informational_gce_units)
        test_plan.hw_test_units.extend(filtered_hw_test_units)
        pres.logs['filtered test plan'] = str(test_plan)

    return test_plan

  def schedule_tests(self, test_plan, passed_tests, timeout,
                     test_to_build_map=None, snapshot=None, is_retry=False,
                     run_async=False, container_metadata=None,
                     require_stable_devices=False):
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
      is_retry (bool): Whether this is a CQ retry.
      run_async (bool): whether to stop and collect, if set we return no
          failures (an empty list).
      container_metadata (ContainerMetadata): Information on container
        images used for test execution.
      require_stable_devices (bool): whether to only run on devices with
        label-device-stable: True

    Returns:
      MetaTestTuple of lists of the tests scheduled.
    """
    test_plan = self._filter_snapshot_test_plan(test_plan)
    skylab_tasks = self._schedule_skylab_tests(
        test_plan,
        passed_tests,
        timeout,
        test_to_build_map,
        is_retry,
        run_async=run_async,
        container_metadata=container_metadata,
        require_stable_devices=require_stable_devices,
        task_per_build_target=self._skylab_task_per_build_target,
    )
    tast_vm_tests = self._schedule_tast_vm_tests(test_plan, passed_tests,
                                                 snapshot, test_to_build_map,
                                                 is_retry, run_async=run_async)

    tast_gce_tests = self._schedule_tast_gce_tests(test_plan, passed_tests,
                                                   snapshot, test_to_build_map,
                                                   is_retry,
                                                   run_async=run_async)

    return self.MetaTestTuple(skylab=skylab_tasks or [], autotest_vm=[],
                              tast_vm=tast_vm_tests or [],
                              tast_gce=tast_gce_tests or [])

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
    hw_results = self.m.skylab.wait_on_suites(test_tasks.skylab, timeout)
    tast_vm_results = list(
        self.m.buildbucket.collect_builds([vt.id for vt in test_tasks.tast_vm],
                                          step_name='collect tast vm tests',
                                          timeout=int(
                                              timeout.seconds)).values())
    tast_gce_results = list(
        self.m.buildbucket.collect_builds([vt.id for vt in test_tasks.tast_gce],
                                          step_name='collect tast GCE tests',
                                          timeout=int(
                                              timeout.seconds)).values())

    return self.MetaTestTuple(skylab=hw_results, autotest_vm=[],
                              tast_vm=tast_vm_results or [],
                              tast_gce=tast_gce_results)

  def get_test_failures(self, test_results):
    """Logs all test failures to the UI and raises on failed tests.

    Args:
      test_results: MetaTestTuple of the tests on the changes.
    Returns:
      list[Failure]: All failures discovered in the given run.
    """
    failures = self.m.failures.get_hw_test_failures(test_results.skylab)
    failures += self.m.failures.get_vm_test_failures(test_results.tast_vm)
    failures += self.m.failures.get_vm_test_failures(test_results.tast_gce)
    return failures

  def _schedule_skylab_tests(self, test_plan, passed_tests, timeout,
                             test_to_build_map=None, is_retry=False,
                             run_async=False, container_metadata=None,
                             require_stable_devices=False,
                             task_per_build_target=False):
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
      run_async (bool): Should the tests be ran async and not cancel
          on the termination of the parent (this caller).
      container_metadata (ContainerMetadata): Information on container
          images used for test execution.
      require_stable_devices (bool): Whether to only run on devices with
          label-device-stable: True
      task_per_build_target (bool): Should we schedule a unique invocation
          of cros_test_platform per build target.

    Returns:
      list[SkylabTask] of the tests scheduled.
    """
    skylab_tasks = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map
    with self.m.step.nest('schedule hardware tests'):
      # A map from {build_target_name: [test_name]}.
      tests_to_run = defaultdict(list)
      hw_build_targets = set()
      for unit in test_plan.hw_test_units:
        for test in unit.hw_test_cfg.hw_test:
          # Do not run non-critical tests on retries.
          if is_retry and not test.common.critical.value:
            continue
          if test.common.display_name not in passed_tests:
            build_target = unit.common.build_target
            test_to_build_map[test.common.display_name] = build_target.name
            tests_to_run[build_target.name].append(
                self.m.skylab.UnitHwTest(unit=unit, hw_test=test))
            hw_build_targets.add(build_target.name)

      _ALL_BUILD_TARGETS = 'all build targets'
      if tests_to_run:
        # If we aren't scheduling per build_target, flatten into one invocation.
        if not task_per_build_target:
          tests_to_run = {_ALL_BUILD_TARGETS: sum(tests_to_run.values(), [])}  #pylint: disable=redefined-variable-type
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
              ))
      self.m.easy.set_properties_step(
          hw_test_build_targets=len(hw_build_targets))
      self.m.easy.set_properties_step(
          hw_test_suites=len(sum(tests_to_run.values(), [])))
    return skylab_tasks

  def _schedule_tast_vm_tests(self, test_plan, passed_tests, snapshot,
                              test_to_build_map=None, is_retry=False,
                              run_async=False):
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
      run_async (bool): Should the tests be ran async and not cancel
          on the termination of the parent (this caller).

    Returns:
      list[Build] objects of the VM tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map

    exps = self.m.cros_infra_config.experiments_for_child_build
    footer_exps = self.m.git_footers.get_footer_values(
        self.m.src_state.gerrit_changes, CROS_EXPERIMENTS_FOOTER,
        step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
    exps.update({x: True for x in footer_exps})

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
                  experiments=exps, properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          TastVmProperties(
                              name=test_name, build_target=build_target,
                              build_payload=unit.common.build_payload,
                              expressions=expressions))),
                  tags=self.m.cros_tags.make_schedule_tags(snapshot),
                  swarming_parent_run_id=None if run_async else
                  self.m.swarming.task_id, can_outlive_parent=run_async))
    vm_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule tast vm tests',
        url_title_fn=self.m.naming.get_build_title)
    return vm_tests

  def _schedule_tast_gce_tests(self, test_plan, passed_tests, snapshot,
                               test_to_build_map=None, is_retry=False,
                               run_async=False):
    """Schedule tast GCE Tests from the test_plan.

    Args:
      test_plan (GenerateTestPlanResponse): A plan for all tests to
          be scheduled.
      passed_tests (list[string]): A list of names for the tests that
          have passed before.
      snapshot (GitilesCommit): Start ref to be supplied to the tests.
      test_to_build_map (dict{string->string}): Map of test names to
          build_targets to be populated.
      is_retry (bool): Whether this is a CQ retry.
      run_async (bool): Should the tests be ran async and not cancel
          on the termination of the parent (this caller).

    Returns:
      list[Build] objects of the GCE tests scheduled.
    """
    requests = []
    test_to_build_map = {} if test_to_build_map is None else test_to_build_map

    for unit in test_plan.tast_gce_test_units:
      for test in unit.tast_gce_test_cfg.tast_gce_test:
        # Do not run non-critical tests on retries.
        if is_retry and not test.common.critical.value:
          continue
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          expressions = [t.test_expr for t in test.tast_test_expr]
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
                  properties=self._with_props_for_child_build(
                      json_format.MessageToDict(
                          GceTestProperties(
                              name=test_name, build_target=build_target,
                              build_payload=unit.common.build_payload,
                              expressions=expressions,
                              gce_metadata=properties_gce_metadata))),
                  tags=self.m.cros_tags.make_schedule_tags(snapshot),
                  swarming_parent_run_id=None if run_async else
                  self.m.swarming.task_id, can_outlive_parent=run_async))
    gce_tests = self.m.buildbucket.schedule(
        requests, step_name='schedule tast GCE tests',
        url_title_fn=self.m.naming.get_build_title)
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
        self._extract_test_summary(
            test_plan.hw_test_units, lambda unit: unit.hw_test_cfg, lambda cfg:
            cfg.hw_test, passed_test_names) + self._extract_test_summary(
                test_plan.vm_test_units, lambda unit: unit.vm_test_cfg, lambda
                cfg: cfg.vm_test, passed_test_names) +
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
