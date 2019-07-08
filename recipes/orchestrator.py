# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'recipe_engine/step',
    'cros_history',
    'cros_infra_config',
    'cros_source',
    'cros_test_plan',
    'cros_version',
    'easy',
    'failures',
    'gerrit',
    'git',
    'gitiles',
    'naming',
    'skylab',
]

from PB.chromite.api.test import VmTestRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties
from PB.recipes.chromeos.test_vm import TestVmProperties

from google.protobuf import json_format
from google.protobuf import struct_pb2

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  validate_refs(properties.update_manifest_refs)

  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  snapshot = api.buildbucket.gitiles_commit
  if not snapshot.project:
    with api.step.nest('fetch snapshot ref'):
      snapshot_sha1 = api.gitiles.fetch_revision(
          'chrome-internal', 'chromeos/manifest-internal', 'snapshot')
      snapshot = common_pb2.GitilesCommit(
          host='chrome-internal.googlesource.com',
          project='chromeos/manifest-internal',
          ref='refs/heads/snapshot',
          id=snapshot_sha1)

  # Point start ref to the input snapshot if specified.
  maybe_update_manifest_ref(api, properties.update_manifest_refs, 'start',
                            snapshot)

  if gerrit_changes and not api.gerrit.changes_are_submittable(gerrit_changes):
    raise api.step.StepFailure('failed to cherry-pick changes, '
                               'please rebase and retry')
  if properties.enable_history and gerrit_changes:
    if properties.assert_singleton:
      with api.step.nest('find inflight orchestrator') as step:
        older_running_builds = api.cros_history.get_matching_builds(
            api.buildbucket.build, status=common_pb2.STARTED,
            start_build_id=api.buildbucket.build.id)
        if len(older_running_builds) > 1:
          # Current build is redundant. Exit with failure.
          step.presentation.step_text = 'found inflight run(s)'
          for build in older_running_builds:
            title = api.naming.get_build_title(build)
            url = api.buildbucket.build_url(build_id=build.id)
            step.presentation.links[title] = url
          raise api.step.StepFailure('current build is redundant, exiting')
        else:
          step.presentation.step_text = 'found no inflight run'


  orchestrator_children = api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder).orchestrator.children
  completed_builds, requests = get_build_plan(
      api, child_builders=orchestrator_children,
      enable_history=properties.enable_history, gerrit_changes=gerrit_changes,
      snapshot=snapshot)

  api.buildbucket.host = api.buildbucket.HOST_PROD_BEEFY
  completed_builds += api.buildbucket.run(
      requests, timeout=60 * 60 * 4, step_name='run builds',
      url_title_fn=api.naming.get_build_title)

  # If this is a dry run, check that the builds passed and quit.
  if api.cq.state == api.cq.DRY:
    api.failures.raise_failed_builds(completed_builds)
    return

  # Otherwise, we have to run tests.
  need_tests_builds = [
      b for b in completed_builds if not api.failures.is_build_failure(b)
  ]

  with api.step.nest('run tests'):
    with api.step.nest('schedule tests'):
      test_plan = api.cros_test_plan.generate(need_tests_builds, snapshot.id)

      # We will not run tests that have already passed for this patch set.
      passed_tests = []
      if properties.enable_history and gerrit_changes:
        passed_tests = api.cros_history.get_passed_tests()

      test_to_build_target_map = {}

      skylab_tasks = schedule_skylab_tests(api, test_plan, passed_tests,
                                           test_to_build_target_map)

      vm_tests = schedule_autotest_vm_tests(api, test_plan, passed_tests,
                                            snapshot, test_to_build_target_map)

      tast_vm_tests = schedule_tast_vm_tests(api, test_plan, passed_tests,
                                             snapshot, test_to_build_target_map)
      vm_tests += tast_vm_tests

      moblab_vm_tests = schedule_moblab_vm_tests(
          api, test_plan, passed_tests, snapshot, test_to_build_target_map)

    with api.step.nest('collect tests'):
      hw_results = []
      if skylab_tasks:
        hw_results = api.skylab.wait_suites(skylab_tasks)

      vm_results = []
      if vm_tests:
        vm_results = api.buildbucket.collect_builds(
            [vt.id for vt in vm_tests], step_name='collect vm tests',
            timeout=60 * 60 * 4).values()

      moblab_vm_results = []
      if moblab_vm_tests:
        moblab_vm_results = api.buildbucket.collect_builds(
            [mvt.id for mvt in moblab_vm_tests],
            step_name='collect moblab vm tests',
            timeout=60 * 60 * 4).values()

      # Record test results.
      passed_tests = [
          hw_result.task.test.common.display_name
          for hw_result in hw_results
          if not api.failures.is_hw_test_failure(hw_result)
      ]
      passed_tests.extend([
          api.naming.get_vm_test_title(vm_result)
          for vm_result in vm_results
          if not api.failures.is_vm_test_failure(vm_result)
      ])
      passed_tests.extend([
          api.naming.get_moblab_vm_test_title(moblab_vm_result)
          for moblab_vm_result in moblab_vm_results
          if not api.failures.is_moblab_vm_test_failure(moblab_vm_result)
      ])
      api.cros_history.set_passed_tests(passed_tests)

  baseline_hw_results = []
  failed_hw_results = [
      hw_result.task.test.common.display_name
      for hw_result in hw_results
      if api.failures.is_hw_test_failure(hw_result)
  ]
  with api.failures.ignore_exceptions():
    if gerrit_changes and needs_baseline_validation(
        failed_hw_results, hw_results,
        properties.baseline_verification_threshold):
      # Start Baseline HW Verification process.
      build_targets_to_verify = set([
          test_to_build_target_map[test_name] for test_name in failed_hw_results
      ])
      baseline_builds_to_verify = [
          build_target + '-baseline' for build_target in build_targets_to_verify
      ]
      _, build_requests = get_build_plan(
          api, child_builders=baseline_builds_to_verify, enable_history=True,
          gerrit_changes=gerrit_changes, snapshot=snapshot)
      baseline_builds = api.buildbucket.run(
          build_requests, timeout=60 * 60 * 4, step_name='run baseline builds',
          url_title_fn=api.naming.get_build_title)
      with api.step.nest('run baseline tests'):
        with api.step.nest('schedule baseline tests'):
          baseline_test_plan = api.cros_test_plan.generate(
              baseline_builds, snapshot.id)
          baseline_skylab_tasks = schedule_skylab_tests(api, baseline_test_plan,
                                                        passed_tests)

        with api.step.nest('collect baseline tests'):
          if baseline_skylab_tasks:
            baseline_hw_results = api.skylab.wait_suites(baseline_skylab_tasks)
            # Add failures here to passed_tests.
            passed_tests.extend([
                hw_result.task.test.common.display_name
                for hw_result in baseline_hw_results
                if api.failures.is_hw_test_failure(hw_result)
            ])

  api.cros_history.set_passed_tests(passed_tests)

  # Verify builds/tests in a deferred context so that all failures appear.
  with api.step.nest('check test results'):
    with api.step.defer_results():
      api.failures.raise_failed_builds(completed_builds)
      api.failures.raise_failed_hw_tests(
          hw_results, baseline_hw_tests=baseline_hw_results)
      api.failures.raise_failed_vm_tests(vm_results)
      api.failures.raise_failed_moblab_vm_tests(moblab_vm_results)

  # Victory! If we've made it this far, the child builders were successful
  # and we can update the success manifest ref if it is specified.
  maybe_update_manifest_ref(api, properties.update_manifest_refs, 'success',
                            snapshot)


def autotest_vm_test(build_target):
  """Returns the autotest builder name for the given build_target."""
  return build_target.name + '-autotest-vm'


def tast_vm_test(build_target):
  """Returns the tast builder name for the given build_target."""
  return build_target.name + '-tast-vm'


def schedule_skylab_tests(api, test_plan, passed_tests, test_to_build_map=None):
  """Schedule skylab tests from the test_plan.

  Args:
    api (RecipeApi): See RunSteps.
    test_plan (GenerateTestPlanResponse): A plan for all tests to
      be scheduled.
    passed_tests (list[string]): A list of names for the tests that
      have passed before.
    test_to_build_map (dict{string->string}): Map of test names to
      build_targets to be populated.

  Returns:
    list[SkylabTask] of the tests scheduled.
  """
  skylab_tasks = []
  test_to_build_map = {} if test_to_build_map is None else test_to_build_map
  with api.step.nest('schedule hardware tests'):
    for unit in test_plan.hw_test_units:
      for test in unit.hw_test_cfg.hw_test:
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          skylab_tasks.append(
              api.skylab.create_suite(test, unit.common.build_payload))

  return skylab_tasks


def schedule_autotest_vm_tests(api, test_plan, passed_tests, snapshot,
                               test_to_build_map=None):
  """Schedule Autotest VM Tests from the test_plan.

  Args:
    api (RecipeApi): See RunSteps.
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
            api.buildbucket.schedule_request(
                gitiles_commit=snapshot, builder=autotest_vm_test(build_target),
                critical=test.common.critical.value,
                properties=with_props_for_child_build(
                    api,
                    json_format.MessageToDict(
                        TestVmProperties(
                            name=test_name, build_target=build_target,
                            test_harness=VmTestRequest.AUTOTEST,
                            build_payload=unit.common.build_payload,
                            expressions=['suite:' + test.test_suite])))))

  vm_tests = api.buildbucket.schedule(requests,
                                      step_name='schedule autotest vm tests')
  return vm_tests


def schedule_tast_vm_tests(api, test_plan, passed_tests, snapshot,
                           test_to_build_map=None):
  """Schedule tast VM Tests from the test_plan.

  Args:
    api (RecipeApi): See RunSteps.
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
            api.buildbucket.schedule_request(
                gitiles_commit=snapshot, builder=tast_vm_test(build_target),
                critical=test.common.critical.value,
                properties=with_props_for_child_build(
                    api,
                    json_format.MessageToDict(
                        TestVmProperties(
                            name=test_name, build_target=build_target,
                            test_harness=VmTestRequest.TAST,
                            build_payload=unit.common.build_payload,
                            expressions=[
                                t.test_expr for t in test.tast_test_expr
                            ])))))

  vm_tests = api.buildbucket.schedule(requests,
                                      step_name='schedule tast vm tests')
  return vm_tests


def schedule_moblab_vm_tests(api, test_plan, passed_tests, snapshot,
                             test_to_build_map=None):
  """Schedule Moblab VM Tests from the test_plan.

  Args:
    api (RecipeApi): See RunSteps.
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
            api.buildbucket.schedule_request(
                gitiles_commit=snapshot, builder='moblab-vm-test',
                critical=test.common.critical.value,
                properties=with_props_for_child_build(
                    api,
                    json_format.MessageToDict(
                        TestMoblabVmProperties(
                            name=test_name,
                            build_payload=unit.common.build_payload,
                        )))))

  moblab_vm_tests = api.buildbucket.schedule(
      requests, step_name='schedule moblab vm tests')
  return moblab_vm_tests


def get_build_plan(api, child_builders, enable_history, gerrit_changes,
                   snapshot):
  """Get a list of builds to be run and  a list of builds that have succeeded.

  This is planned to be replaced by a Go binary.

  Args:
    api (RecipeApi): See RunSteps documentation.
    child_builders (list[string]): List of builder names of the child
      builders.
    enable_history (bool): Enables history lookup in cq orchestrator.
    gerrit_changes list(GerritChange): List of patches in the order that they
      can be cherry-picked.
    snapshot (GitilesCommit): Start ref to be supplied to the child builds.

  Returns:
    A tuple of two lists: a list of build_pb2.Build objects of successful
    builds with refreshed criticality and a list of ScheduleBuildRequest of
    the builds that have to be scheduled.
  """
  completed_builds = []
  passed_builders = set()
  requests = []
  retry_count = 0

  if enable_history and gerrit_changes:
    with api.step.nest('get build history for changes'):
      retry_count = len(
          api.cros_history.get_matching_builds(api.buildbucket.build,
                                               status=common_pb2.FAILURE))
      completed_builds = get_completed_builds(api, child_builders)
      passed_builders = set(build.builder.builder for build in completed_builds)

  for child in child_builders:
    if child not in passed_builders:
      child_builder_config = api.cros_infra_config.get_builder_config(child)
      critical = child_builder_config.general.critical.value
      if critical == common_pb2.YES or retry_count == 0:
        # Applies to CQ only. Retry just the critical builds.
        requests.append(
            api.buildbucket.schedule_request(
                gitiles_commit=snapshot, builder=child, critical=critical,
                properties=api.cq.props_for_child_build))

  return completed_builds, requests


def get_completed_builds(api, cq_orch_children):
  """Get the list of previously passed child builds with criticality refreshed.

  Args:
    api (RecipeApi): See RunSteps documentation.
    cq_orch_children list(str): List of child builders of cq-orchestrator.
        e.g. [u'arkham-cq', u'reef-cq', ...]

  Returns:
    A list of build_pb2.Build objects corresponding to the
    latest successful child builds with the same patches as the current
    cq orchestrator with refreshed critical values.
  """
  completed_builds = []
  passed_builds = api.cros_history.get_passed_builds()
  for build in passed_builds:
    # Filter out non-child builds like vm_test, dry run orchestrator or
    # hw_tests in the future.
    if build.builder.builder in cq_orch_children:
      builder_config = api.cros_infra_config.get_builder_config(
          build.builder.builder)
      # Refresh the criticality of the builders.
      build.critical = builder_config.general.critical.value
      completed_builds.append(build)

  return completed_builds


def validate_refs(refs):
  """Assert the given refs start with refs/heads.

  Args:
    refs (UpdateManifestRefs): Refs to validate.

  Raises:
    AssertionError: If any invalid ref is found.
  """
  validate_ref(refs.start, 'start')
  validate_ref(refs.success, 'success')


def needs_baseline_validation(failed_results, all_results, threshold):
  """Check if we need baseline validation for this orchestrator.

  Args:
    failed_results (list[SkylabResults]): Results of failed tests.
    all_results (list[SkylabResults]): Results of all tests.
    threshold (float): upper threshold for baseline validation.

  Returns:
    A boolean indicating whether we need to initiate baseline
    validation.
  """
  needs_validation = False
  # If either all_results or failed_results is empty, there is no work
  # to be done.
  if failed_results:
    failure_ratio = float(len(failed_results)) / len(all_results)
    if failure_ratio <= threshold:
      needs_validation = True

  return needs_validation


def validate_ref(ref, name):
  """Assert the given ref starts with refs/heads.

  Args:
    ref (string): the ref to validate, if any.
    name (string): name of ref to validate.
  """
  if ref and not ref.startswith('refs/heads/'):
    raise ValueError('%s ref %s is missing refs/heads/' % (name, ref))


def maybe_update_manifest_ref(api, update_manifest_refs, name, commit):
  """Update ref in manifest-internal to point to current snapshot.

  Args:
    api (RecipeApi): See RunSteps documentation.
    update_manifest_refs (UpdateManifestRefs): refs to maybe update.
    name (string): name of ref to maybe update. Must correspond to
        a property name on update_manifest_refs.
    commit (GitilesCommit): The commit to update the manifest ref to.
  """
  assert commit.project, 'malformed gitiles commit: %r' % commit
  ref = getattr(update_manifest_refs, name)
  if ref:
    with api.step.nest('update manifest %s ref' % name):
      checkout_path = api.path.mkdtemp()
      with api.context(cwd=checkout_path):
        git_repo = 'https://%s/%s' % (commit.host, commit.project)
        api.git.clone(git_repo)
        api.git.fetch_ref(git_repo, commit.id)
        refspec = '%s:%s' % (commit.id, ref)
        api.git.push(git_repo, refspec)


def with_props_for_child_build(api, properties):
  """Merge 'properties' and 'api.cq.props_for_child_build'.

  Should be used to insert 'props_for_child_build' into properties being passed
  to a Buildbucket request.

  Args:
    api (RecipeApi): See RunSteps documentation.
    properties (dict): A dictionary of properties.

  Return:
    The merged dict.
  """
  properties.update(api.cq.props_for_child_build)
  return properties


def GenTests(api):

  def postsubmit_orchestrator_build():
    """Generate a test build proto for the postsubmit orchestrator."""
    return api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                    builder='postsubmit-orchestrator')

  def postsubmit_orchestrator_build_with_no_gitiles():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos',
                                             bucket='postsubmit',
                                             builder='postsubmit-orchestrator')
    build.input.gitiles_commit.Clear()
    return api.buildbucket.build(build)

  def cq_orchestrator_build_with_gerrit_change():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder='cq-orchestrator')
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return api.buildbucket.build(build)

  def vm_test_build(name):
    output = build_pb2.Build.Output()
    output.properties.update({'name': name})
    return build_pb2.Build(output=output, status=common_pb2.SUCCESS)

  def build_target_property(build_target):
    """Generate a struct for the 'build_target' property.

    Args:
      * build_target (str): The name of the build target.
    """
    return struct_pb2.Struct(
        fields={
            'build_target':
                struct_pb2.Value(
                    struct_value=struct_pb2.Struct(fields={
                        'name': struct_pb2.Value(string_value=build_target)
                    }))
        })

  vm_tests = [
      vm_test_build('vm-test'),
  ]

  moblab_vm_tests = [
      vm_test_build('moblab-vm-test'),
  ]

  yield (api.test('basic') + postsubmit_orchestrator_build() +
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  builds = [
      build_pb2.Build(
          id=8922054662172514000, builder={'builder': 'amd64-generic-cq'},
          status=common_pb2.SUCCESS,
          input=dict(properties=build_target_property('amd64-generic'))),
      build_pb2.Build(
          id=8922054662172514001, builder={'builder': 'arm-generic-cq'},
          status=common_pb2.SUCCESS,
          input=dict(properties=build_target_property('arm-generic'))),
  ]

  yield (api.test('fails_if_changes_not_submittable') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.gerrit.simulated_changes_are_submittable(submittable=False))

  yield (api.test('builds_with_history') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.buildbucket.simulated_search_results(
             builds, 'get build history for changes.'
             'get change build history.buildbucket.search') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('tests_with_history') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.buildbucket.simulated_search_results(
             [], 'get build history for changes.'
             'get change build history.buildbucket.search') +  #
         api.buildbucket.simulated_search_results(
             [api.cros_history.build_with_passed_tests(['nami/hw/bvt-cq'])],
             'run tests.schedule tests.get change test history'
             '.find matching builds.buildbucket.search') +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('fails_if_inflight_orchs') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.properties(assert_singleton=True) +  #
         api.buildbucket.simulated_search_results(
             builds, step_name='find inflight orchestrator.'
             'find matching builds.buildbucket.search'))

  yield (api.test('runs_if_no_inflight_orchs') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.properties(assert_singleton=True) +  #
         api.buildbucket.simulated_search_results(
             [], step_name='find inflight orchestrator.'
             'find matching builds.buildbucket.search') +
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('retry_only_critical_builds') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.buildbucket.simulated_search_results(
             builds, step_name='get build history for changes'
             '.find matching builds.buildbucket.search') +
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('updates_refs') +  #
         postsubmit_orchestrator_build() +  #
         api.properties(update_manifest_refs={
             'start': 'refs/heads/foo',
             'success': 'refs/heads/bar'
         }) +
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('missing_gitiles_commit') +  #
         postsubmit_orchestrator_build_with_no_gitiles() +
         api.properties(update_manifest_refs={
             'start': 'refs/heads/foo',
             'success': 'refs/heads/bar'
         }) +
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('bad_update_ref') +  #
         api.properties(update_manifest_refs={'start': 'foo'}) +  #
         api.expect_exception("ValueError"))

  yield (api.test('dry_run') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(dry_run=True))

  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.FAILURE, critical=common_pb2.YES),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-postsubmit'},
                      status=common_pb2.SUCCESS, critical=common_pb2.NO),
  ]
  yield (api.test('critical_child_builder_fails') +  #
         postsubmit_orchestrator_build() +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.SUCCESS, critical=common_pb2.YES),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-postsubmit'},
                      status=common_pb2.FAILURE, critical=common_pb2.NO),
  ]
  yield (api.test('non-critical_child_builder_fails') +  #
         postsubmit_orchestrator_build() +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  skylab_results = [
      api.swarming.task_result(id='bvt-cq-task-id', name='success_task',
                               state=api.swarming.TaskState.COMPLETED),
      api.swarming.task_result(id='bvt-inline-task-id', name='failed_task',
                               state=api.swarming.TaskState.COMPLETED,
                               failure=True)
  ]
  baseline_results_failure = [
      api.swarming.task_result(id='bvt-inline-task-id', name='failed_task',
                               state=api.swarming.TaskState.COMPLETED,
                               failure=True)
  ]
  yield (api.test('pass_with_baseline_validation') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.properties(baseline_verification_threshold=1.0) +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests') +
         api.override_step_data('run tests.collect tests.collect skylab tasks',
                                api.swarming.collect(skylab_results)) +  #
         api.override_step_data(
             'run baseline tests.collect baseline tests'
             '.collect skylab tasks',
             api.swarming.collect(baseline_results_failure)))

  baseline_results_success = [
      api.swarming.task_result(id='bvt-inline-task-id', name='failed_task',
                               state=api.swarming.TaskState.COMPLETED)
  ]
  yield (api.test('fail_with_baseline_validation') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.properties(baseline_verification_threshold=1.0) +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests') +
         api.override_step_data('run tests.collect tests.collect skylab tasks',
                                api.swarming.collect(skylab_results)) +  #
         api.override_step_data(
             'run baseline tests.collect baseline tests'
             '.collect skylab tasks',
             api.swarming.collect(baseline_results_success)))
