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
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_relevance',
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
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties
from PB.recipes.chromeos.test_vm import TestVmProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

from google.protobuf import json_format
from google.protobuf import struct_pb2

from collections import defaultdict

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  api.buildbucket.host = api.buildbucket.HOST_PROD_BEEFY

  validate_refs(properties.update_manifest_refs)
  api.cros_bisect.set_orchestrator_bisect_builder()

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
            api.buildbucket.build, statuses=[common_pb2.STARTED])
        if len(older_running_builds) > 1:
          # Current build is redundant (Yourself + Another). Exit with failure.
          step.presentation.step_text = 'found inflight run(s)'
          for build in older_running_builds:
            title = api.naming.get_build_title(build)
            url = api.buildbucket.build_url(build_id=build.id)
            step.presentation.links[title] = url
          raise api.step.StepFailure('current build is redundant, exiting')
        else:
          step.presentation.step_text = 'found no inflight run'

  child_builders = get_child_builders(api)

  with api.step.nest('run builds'):
    completed_builds = filter_schedule_wait_builds(api, child_builders,
                                                   properties.enable_history,
                                                   snapshot, gerrit_changes)

  # From here all builds should have been collected: move to checking results.
  with api.step.nest('check build results'):
    failures = api.failures.get_build_failures(completed_builds)

  # If this is a dry run, check that the builds passed and quit.
  if api.cq.state == api.cq.DRY:
    return api.failures.aggregate_failures(failures)

  # Otherwise, we have to run tests.
  need_tests_builds = [
      b for b in completed_builds if not api.failures.is_build_failure(b)
  ]

  with api.step.nest('run tests'):
    with api.step.nest('schedule tests'):
      test_plan = get_test_plan(api, need_tests_builds, snapshot)

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
        hw_results = api.skylab.wait_tasks(skylab_tasks)

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

  baseline_hw_results = []
  baseline_vm_results = []
  failed_test_names = ([
      hw_result.task.test.common.display_name
      for hw_result in hw_results
      if api.failures.is_hw_test_failure(hw_result)
  ] + [
      api.naming.get_vm_test_title(vm_result)
      for vm_result in vm_results
      if api.failures.is_vm_test_failure(vm_result)
  ])

  with api.failures.ignore_exceptions():
    if gerrit_changes and needs_baseline_validation(
        failed_test_names, test_plan, properties.baseline_validation_percent,
        properties.baseline_validation_count):
      # Start Baseline HW Verification process.
      build_targets_to_verify = set([
          test_to_build_target_map[test_name] for test_name in failed_test_names
      ])
      baseline_builds = []
      for build in completed_builds:
        # Assuming that completed_builds have build_targets.
        build_target = api.cros_history.get_build_target(build)
        if build_target and build_target in build_targets_to_verify:
          baseline_builds += api.cros_history.get_snapshot_builds(
              build.input.gitiles_commit, [build_target + '-snapshot'],
              [common_pb2.SUCCESS])

      with api.step.nest('run baseline tests'):
        with api.step.nest('schedule baseline tests'):
          baseline_test_plan = api.cros_test_plan.generate(
              baseline_builds, snapshot.id)
          baseline_skylab_tasks = schedule_skylab_tests(api, baseline_test_plan,
                                                        passed_tests, bb=True)
          baseline_vm_tests = schedule_autotest_vm_tests(
              api, baseline_test_plan, passed_tests, snapshot)
          baseline_vm_tests += schedule_tast_vm_tests(api, baseline_test_plan,
                                                      passed_tests, snapshot)

        with api.step.nest('collect baseline tests'):
          if baseline_skylab_tasks:
            baseline_hw_results = api.skylab.wait_tasks(baseline_skylab_tasks,
                                                        bb=True)
            # Add failures here to passed_tests.
            passed_tests.extend([
                hw_result.task.test.common.display_name
                for hw_result in baseline_hw_results
                if api.failures.is_hw_test_failure(hw_result)
            ])
          if baseline_vm_tests:
            baseline_vm_results = api.buildbucket.collect_builds(
                [vt.id for vt in baseline_vm_tests],
                step_name='collect baseline vm tests',
                timeout=60 * 60 * 4).values()
            # Add failures here to passed_tests.
            passed_tests.extend([
                api.naming.get_vm_test_title(vm_result)
                for vm_result in baseline_vm_results
                if api.failures.is_vm_test_failure(vm_result)
            ])

  api.cros_history.set_passed_tests(passed_tests)

  # Verify builds/tests in a deferred context so that all failures appear.
  with api.step.nest('check test results'):
    api.cros_bisect.set_test_failures(hw_results)
    failures.extend(
        api.failures.get_hw_test_failures(hw_results, baseline_hw_results))
    failures.extend(
        api.failures.get_vm_test_failures(vm_results, baseline_vm_results))
    # TODO(evanhernandez): Include Moblab VM tests here once stable.
    # Also, add Moblab to baseline validation pipeline.

  # Victory! If we've made it this far, the child builders were successful
  # and we can update the success manifest ref if it is specified.
  maybe_update_manifest_ref(api, properties.update_manifest_refs, 'success',
                            snapshot)

  return api.failures.aggregate_failures(failures)

def get_child_builders(api):
  """Returns the child builders that should be run for this invocation.

  Args:
    api (RecipeApi): See RunSteps.

  Returns:
    list[string] of child builder names to run
  """
  child_builders = api.cros_bisect.get_test_child_builders()
  if child_builders:
    return child_builders
  return api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder).orchestrator.children

def get_test_plan(api, builds, snapshot):
  """Returns the test plan that should be executed for this invocation.

  Args:
    api (RecipeApi): See RunSteps.
    builds (list[build_pb2.Build]): builds to test.
    snapshot (GitilesCommit): Start ref of the child builds.
  """
  # TODO(dburger): alternatively pull test plan from FindIt
  # bisect invocation properties.
  return api.cros_test_plan.generate(builds, snapshot.id)

def autotest_vm_test(build_target):
  """Returns the autotest builder name for the given build_target."""
  return build_target.name + '-autotest-vm'


def tast_vm_test(build_target):
  """Returns the tast builder name for the given build_target."""
  return build_target.name + '-tast-vm'


def schedule_skylab_tests(api, test_plan, passed_tests, test_to_build_map=None,
                          bb=False):
  """Schedule skylab tests from the test_plan.

  Args:
    api (RecipeApi): See RunSteps.
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
  with api.step.nest('schedule hardware tests'):
    for unit in test_plan.hw_test_units:
      for test in unit.hw_test_cfg.hw_test:
        if test.common.display_name not in passed_tests:
          test_name = test.common.display_name
          build_target = unit.common.build_target
          test_to_build_map[test_name] = build_target.name
          skylab_tasks.append(api.skylab.create_suite(test, unit, bb=bb))

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


def filter_schedule_wait_builds(api, child_builders, enable_history, snapshot,
                                gerrit_changes):
  """Find the builds you need, filter those already started, run, and collect.

  Most of the heavy lifting is done in get_build_plan.

  Args:
    api (RecipeApi): See RunSteps documentation.
    child_builders (list(string)): A list of builders.
    enable_history (bool): Enables history lookup in cq orchestrator.
    snapshot (GitilesCommit): Start ref to be supplied to the child builds.
    gerrit_changes list(GerritChange): List of patches in the order that they
      can be cherry-picked.

  Returns: A list of build_pb2.Build objects with build results.
  """
  completed_builds, existing_builds, new_build_requests = get_build_plan(
      api, child_builders=child_builders, enable_history=enable_history,
      gerrit_changes=gerrit_changes, snapshot=snapshot)

  # request new builds and add to total existing.
  existing_builds += api.buildbucket.schedule(
      new_build_requests, url_title_fn=lambda x: "schedule builds")

  # collect all existing builds, add to completed builds
  completed_builds += api.buildbucket.collect_builds(
      [b.id for b in existing_builds], timeout=60 * 60 * 4, step_name='collect',
      url_title_fn=api.naming.get_build_title).values()

  return completed_builds


def prioritize_builds(api, builds):
  """Takes a list of builds and dedups, choosing a best build, dropping others.

  See build_orderer for the sort order. This is most useful if you have
  multiple, identical, builds and you want to choose a single one from each
  builder type to carry forward.

  Args:
    builds ([build_pb2.Build]): Builds to dedupe and sort.

  Returns: A list of build_pb2.Build objects, deduped and prioritized.
  """

  def build_orderer(b1, b2):
    if b1.status == common_pb2.SUCCESS and b2.status != common_pb2.SUCCESS:
      return -1
    elif b2.status == common_pb2.SUCCESS and b1.status != common_pb2.SUCCESS:
      return 1
    else:
      # otherwise get the earliest created, which will be reasonable for
      # running builds and scheduled builds if scheduling is fair.
      return int(b1.create_time.seconds - b2.create_time.seconds)

  # add all of them to dict: build_target -> build proto
  build_map = defaultdict(list)
  for b in builds:
    bt = api.cros_history.get_build_target(b)
    if bt:
      build_map[bt].append(b)

  best_builds_list = []
  for _, build_list in build_map.items():
    best_build = sorted(build_list, cmp=build_orderer)[0]  # [0] most preferable
    best_builds_list.append(best_build)

  # return reduced list
  return best_builds_list


def get_build_plan(api, child_builders, enable_history, gerrit_changes,
                   snapshot):
  """Return a three-tuple of builds, completed, existing, and needed.

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
    A tuple of three lists:
      A list of Build objects of successful builds with refreshed criticality.
      A list of identical builds we don't need to schedule and can join.
      A list of ScheduleBuildRequests that have to be scheduled.
  """
  filter_log = []
  completed_builds, existing_builds, new_build_requests = [], [], []
  retry_count = 0

  image_builders_pointless = False
  if gerrit_changes:
    image_builders_pointless = (
        api.cros_relevance.are_all_image_builders_pointless(
            gerrit_changes, snapshot,
            name='orchestrator pointless build check'))

  if enable_history and gerrit_changes:
    with api.step.nest('get build history for changes'):
      retry_count = len(
          api.cros_history.get_matching_builds(api.buildbucket.build,
                                               statuses=[common_pb2.FAILURE]))
      completed_builds = get_completed_builds(api, child_builders)

  existing_builds = api.cros_history.get_snapshot_builds(
      snapshot, child_builders,
      [common_pb2.SUCCESS, common_pb2.SCHEDULED, common_pb2.STARTED],
      patches=gerrit_changes)

  # Find number of builds, make set of builders, prioritize and log.
  initial_found_builds = len(existing_builds)
  existing_builds = prioritize_builds(api, existing_builds)
  filter_log.append(
      'from {} -> {} joinable after dedup and prioritization'.format(
          initial_found_builds, len(existing_builds)))

  completed_build_targets = \
      api.cros_history.build_target_set(completed_builds)
  existing_build_targets = \
      api.cros_history.build_target_set(existing_builds)

  with api.step.nest('filter builds') as step:
    for child in child_builders:

      # now we have a list of build names such as ['buddy-postsubmit', ...]
      # whereas existing_builds and completed_builds might be postfixed
      # with -snapshot. Use this to filter out.
      # TODO(crbug/991996): Refactor: use something other than string manip.
      child_target = child[:child.rfind('-')]  # i.e. wizpig-snapshot -> wizpig
      # No need to retry previously-passed builds.
      if child_target in completed_build_targets:
        filter_log.append('{} already passed'.format(child_target))
        continue
      # We've already found an existing build, we'll just wait on it later.
      elif child_target in existing_build_targets:
        filter_log.append('{} exists, will join on it'.format(child_target))
        continue

      child_builder_config = api.cros_infra_config.get_builder_config(child)

      # Don't do child builds that are unaffected by the gerrit_changes. The
      # IMAGE_ZIP check makes this check only apply to those builders that
      # produce Chrome OS builds, without affecting special builders like the
      # chromite unit test ones.
      image_zip = BuilderConfig.Artifacts.IMAGE_ZIP
      if image_builders_pointless and (image_zip in
          child_builder_config.artifacts.artifact_types):
        filter_log.append('{} build is irrelevant for changes'.format(child))
        continue

      # Don't retry non-critical builds.
      critical = child_builder_config.general.critical.value
      if not critical and retry_count != 0:
        filter_log.append('{} is non-critical and already ran'.format(child))
        continue

      tags = [{
          'key': 'parent_buildbucket_id',
          'value': str(api.buildbucket.build.id)
      }]

      new_build_requests.append(
          api.buildbucket.schedule_request(
              gitiles_commit=snapshot, builder=child, critical=critical,
              properties=api.cq.props_for_child_build, tags=tags))
    step.presentation.logs['filter log'] = filter_log

  return completed_builds, existing_builds, new_build_requests


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


def needs_baseline_validation(failed_results, test_plan, percent_threshold,
                              count_threshold):
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
    if (failure_ratio <= float(percent_threshold)/100 or
        len(failed_results) <= count_threshold):
      return True

  return False


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

  def input_proto(snapshot, build_target):
    """Generate an instance of Build.Input.

    Args:
      * snapshot(GitilesCommit): The snapshot of the build.
      * build_target (str): The name of the build target.
    """
    return build_pb2.Build.Input(
        properties=api.cros_history.build_target_property(build_target),
        gitiles_commit=snapshot)

  vm_tests = [
      vm_test_build('vm-test'),
  ]

  moblab_vm_tests = [
      vm_test_build('moblab-vm-test'),
  ]

  hw_tests = {
      'results': [
          api.skylab.wait_task_result(id='bvt-cq-task-id', name='hw test1',
                                      success=True),
          api.skylab.wait_task_result(id='bvt-inline-task-id', name='hw test2',
                                      success=True),
      ]
  }

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'arm-generic')),
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      status=common_pb2.STARTED, input=input_proto(
                          None, 'atlas')),
  ]

  # we have three here to properly exercise "prioritize_builds"
  existing_annealing_builds = [
      build_pb2.Build(id=8922054662172514002, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514003, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514005, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS,
                      input=dict(properties=struct_pb2.Struct())),  # no bt
      build_pb2.Build(id=8922054662172514004, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SCHEDULED, input=input_proto(None, 'amd64-generic')),
  ]

  yield (api.test('basic') + postsubmit_orchestrator_build() +
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('fails_if_changes_not_submittable') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.gerrit.simulated_changes_are_submittable(submittable=False))

  yield (api.test('builds_with_history') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.buildbucket.simulated_search_results(
             builds, 'run builds.get build history for changes.'
             'get change build history.buildbucket.search') +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('pointless_builds') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check',
             build_is_pointless=True) +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('joinable_existing_annealing_builds') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.buildbucket.simulated_search_results(
             existing_annealing_builds, 'run builds.get snapshot builds'
             '.buildbucket.search') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
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
             [], 'run builds.get build history for changes.'
             'get change build history.buildbucket.search') +  #
         api.buildbucket.simulated_search_results(
             [api.cros_history.build_with_passed_tests(['nami/hw/bvt-cq'])],
             'run tests.schedule tests.get change test history'
             '.find matching builds.buildbucket.search') +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
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
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.buildbucket.simulated_search_results(
             [], step_name='find inflight orchestrator.'
             'find matching builds.buildbucket.search') +
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
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
         }) + api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
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
         }) + api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
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
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.cq(dry_run=True))

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-postsubmit'
      }, status=common_pb2.FAILURE, critical=common_pb2.NO, input=input_proto(
          None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-postsubmit'
      }, status=common_pb2.SUCCESS, critical=common_pb2.NO, input=input_proto(
          None, 'arm-generic')),
  ]

  yield (api.test('retry_only_critical_builds') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.buildbucket.simulated_search_results(
             builds, step_name='run builds.get build history for changes'
             '.find matching builds.buildbucket.search') +
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.FAILURE, critical=common_pb2.YES),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-postsubmit'},
                      status=common_pb2.SUCCESS, critical=common_pb2.NO),
  ]
  yield (
      api.test('critical_child_builder_fails') +  #
      postsubmit_orchestrator_build() +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') + api.easy.simulate_json_step(
              'run tests.collect tests.'
              'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
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
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  builds = [
      build_pb2.Build(
          id=8922054662172514000,
          builder={'builder': 'amd64-generic-postsubmit'},  #
          status=common_pb2.SUCCESS,
          critical=common_pb2.YES,
          input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(
          id=8922054662172514001,
          builder={'builder': 'arm-generic-postsubmit'},  #
          status=common_pb2.FAILURE,
          critical=common_pb2.NO,
          input=input_proto(common_pb2.GitilesCommit(), 'target')),
  ]
  hw_tests = {
      'results': [
          api.skylab.wait_task_result(id='bvt-cq-task-id', name='hw test1',
                                      success=True),
          api.skylab.wait_task_result(id='bvt-inline-task-id', name='hw test2',
                                      success=False),
      ]
  }
  baseline_results_failure = {
      'results': [
          api.skylab.wait_task_result(id='bvt-inline-task-id', name='hw test2',
                                      success=False),
      ]
  }

  yield (api.test('does_not_run_baseline_validation') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.properties(baseline_validation_percent=0) +  #
         api.properties(baseline_validation_limit=0) +  #
         api.cros_relevance.simulate_run_pointless_build_checker(
             name='run builds.orchestrator pointless build check') +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests, step_name='run tests.collect tests.collect vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (
      api.test('pass_with_baseline_validation') +  #
      cq_orchestrator_build_with_gerrit_change() +  #
      api.properties(baseline_validation_percent=100) +  #
      api.cros_relevance.simulate_run_pointless_build_checker(
          name='run builds.orchestrator pointless build check') +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests, step_name='run tests.collect tests.collect vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' baseline vm tests') + api.buildbucket.simulated_collect_output(
              moblab_vm_tests,
              step_name='run tests.collect tests.collect moblab vm tests') +
      api.easy.simulate_json_step(
          'run baseline tests.collect baseline tests.'
          'collect skylab tasks.skylab wait-tasks', baseline_results_failure))

  baseline_results_success = {
      'results': [
          api.skylab.wait_task_result(id='bvt-inline-task-id', name='hw test2',
                                      success=True),
      ]
  }
  yield (
      api.test('fail_with_baseline_validation') +  #
      cq_orchestrator_build_with_gerrit_change() +  #
      api.properties(baseline_validation_percent=100) +  #
      api.cros_relevance.simulate_run_pointless_build_checker(
          name='run builds.orchestrator pointless build check') +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests, step_name='run tests.collect tests.collect vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' baseline vm tests') + api.buildbucket.simulated_collect_output(
              moblab_vm_tests,
              step_name='run tests.collect tests.collect moblab vm tests') +
      api.easy.simulate_json_step(
          'run baseline tests.collect baseline tests.'
          'collect skylab tasks.skylab wait-tasks', baseline_results_success))

  yield (api.test('with_test_bisection_invocation') + #
      postsubmit_orchestrator_build() + #
      api.properties(**{
          '$chromeos/cros_bisect': CrosBisectProperties(test={
              'hw_test_failures': [
                  {'test_spec':
                   api.cros_bisect.serialized_hw_test_unit('amd64-generic')},
              ],
          })
      }) +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests, step_name='run tests.collect tests.collect vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))
