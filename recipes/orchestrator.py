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
    'cros_tags',
    'cros_test_proctor',
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
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties
from PB.recipes.chromeos.test_vm import TestVmProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

from google.protobuf import json_format
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2

from collections import defaultdict
from datetime import datetime

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  api.buildbucket.host = api.buildbucket.HOST_PROD_BEEFY

  with api.step.nest('set up orchestrator'):
    validate_refs(properties.update_manifest_refs)
    api.cros_bisect.set_orchestrator_bisect_builder()

    gerrit_changes = api.buildbucket.build.input.gerrit_changes

    snapshot = api.buildbucket.gitiles_commit
    if not snapshot.project:
      with api.step.nest('fetch snapshot ref'):
        orchestrator_config = api.cros_infra_config.get_builder_config(
          api.buildbucket.build.builder.builder).orchestrator
        # No gitiles_commit from buildbucket: use the default.
        if orchestrator_config.gitiles_commit.project:
          # If we are using the defauilt gitiles_commit, then also use the
          # default CL list.  To override the default CL list, the user must
          # specify a gitiles commit.  We need to convert from our copies of the
          # buildbucket types.
          def ConvertPB(inpb, typ):
            """Convert |inpb| to |typ|."""
            outpb = typ();
            outpb.ParseFromString(inpb.SerializeToString());
            return outpb

          snapshot = ConvertPB(orchestrator_config.gitiles_commit,
                               common_pb2.GitilesCommit)
          gerrit_changes = [ConvertPB(x, common_pb2.GerritChange)
                            for x in orchestrator_config.gerrit_changes]
        else:
          # No default was found in the builder config.  Use a fall-back,
          # hard-coded default.
          snapshot = common_pb2.GitilesCommit(
              host='chrome-internal.googlesource.com',
              project='chromeos/manifest-internal', ref='refs/heads/snapshot')
        # The gitiles_commit we have may not have an id, which will be needed
        # later.  If we need to, re-create the snapshot with the right id.
        if not snapshot.id:
          snapshot = common_pb2.GitilesCommit(
              host=snapshot.host, project=snapshot.project,
              ref=snapshot.ref, id=api.gitiles.fetch_revision(
                  snapshot.host, snapshot.project, snapshot.ref))

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

        # remove yourself potentially.
        older_running_builds = [
            b for b in older_running_builds if b.id != api.buildbucket.build.id
        ]

        # Is a run of the same configuration ongoing? If so, inform and join().
        if len(older_running_builds) > 0:
          step.presentation.step_text = 'found {} inflight run(s) to wait on'\
                                        .format(len(older_running_builds))

          # Give the UI the links to STARTED builds with same configuration.
          for build in older_running_builds:
            title = api.naming.get_build_title(build)
            url = api.buildbucket.build_url(build_id=build.id)
            step.presentation.links[title] = url

          # Wait for all started builds.
          api.buildbucket.collect_builds(
              [b.id for b in older_running_builds],
              step_name='waiting for existing runs',
              timeout=60 * 60 * 23,
          )
        else:
          step.presentation.step_text = 'found no inflight run'

  child_builders = []
  with api.step.nest('run builds') as step:
    child_builders = get_child_builders(api)
    completed_builds = filter_schedule_wait_builds(api, step, child_builders,
                                                   properties.enable_history,
                                                   snapshot, gerrit_changes)

  # From here all builds should have been collected: move to checking results.
  with api.step.nest('check build results') as step:
    for build in completed_builds:
      if build.status in (common_pb2.STARTED, common_pb2.SCHEDULED):
        step.presentation.text = 'some builds are running/pending'
    failures = api.failures.get_build_failures(completed_builds)

  # Recheck the BuilderConfigs at HEAD to see if any failed builds are now
  # non-critical. Snapshot builds are always scheduled without the critical bit
  # set to `NO` so this is also the only place that we will discover that.
  with api.step.nest('non-critical build check') as step:
    api.cros_infra_config.force_reload()
    fresh_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        step, failures, fresh_builder_configs)
  fatal_failures = [f for f in failures if f.fatal == True]

  if not fatal_failures:
    # If we've made it this far, the child builders were successful
    # and we can update the build success manifest ref if it is specified.
    maybe_update_manifest_ref(api, properties.update_manifest_refs, 'build',
                              snapshot)

  # If this is a dry run, check that the builds passed and quit.
  if api.cq.state == api.cq.DRY:
    return api.failures.aggregate_failures(failures)

  # Otherwise, run tests for builds that weren't build failures and that
  # still exist as builders.
  need_tests_builds = [
      b for b in completed_builds if b.status == common_pb2.SUCCESS and
      fresh_builder_configs.get(b.builder.builder)
  ]

  test_failures = api.cros_test_proctor.run_proctor(
      need_tests_builds, snapshot, gerrit_changes, properties.enable_history)
  failures.extend(test_failures)

  # Victory! If we've made it this far, all tests were successful
  # and we can update the test success manifest ref if it is specified.
  maybe_update_manifest_ref(api, properties.update_manifest_refs, 'test',
                            snapshot)

  with api.step.nest('clean up orchestrator') as step:
    # Recheck the BuilderConfigs at HEAD, one last time, to see if any failed
    # builders are now noncritical.
    api.cros_infra_config.force_reload()
    fresh_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        step, failures, fresh_builder_configs)
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


def filter_schedule_wait_builds(api, parent_step, child_builders,
                                enable_history, snapshot, gerrit_changes):
  """Find the builds you need, filter those already started, run, and collect.

  Most of the heavy lifting is done in get_build_plan.

  Args:
    api (RecipeApi): See RunSteps documentation.
    parent_step (Step): the calling step, to be used for presentation purposes.
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
  parent_step.presentation.step_text = ('{} new, {} recycled'.format(
      len(new_build_requests),
      len(completed_builds) + len(existing_builds)))

  # request new builds and add to total existing.
  existing_builds += api.buildbucket.schedule(
      new_build_requests, url_title_fn=api.naming.get_build_title)

  # collect all existing builds, add to completed builds
  try:
    completed_builds += api.buildbucket.collect_builds(
        [b.id for b in existing_builds], timeout=60 * 60 * 36,
        step_name='collect', url_title_fn=api.naming.get_build_title).values()
  except api.step.StepFailure:  #pragma: no cover
    completed_builds += api.buildbucket.get_multi(
        [b.id for b in existing_builds], step_name='get',
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
      A list of -snapshot builds we don't need to schedule and can join.
      A list of ScheduleBuildRequests that have to be scheduled.
  """
  filter_log = []
  completed_builds, snapshot_builds, new_build_requests = [], [], []
  is_retry = False

  builder_configs = [
      api.cros_infra_config.get_builder_config(b) for b in child_builders
  ]
  necessary_builders = api.cros_relevance.get_necessary_builders(
      builder_configs, gerrit_changes, snapshot,
      test_builder_ids=[b.id for b in builder_configs if 'pointless' not in b.id.name])

  if enable_history and gerrit_changes:
    with api.step.nest('get build history') as step:
      is_retry = len(
          api.cros_history.get_matching_builds(api.buildbucket.build)) > 1
      completed_builds = get_completed_builds(api, child_builders)
      step.presentation.step_text = ('found {} build{} to recycle'.format(
          len(completed_builds), '' if len(completed_builds) == 1 else 's'))

  snapshot_builds = api.cros_history.get_snapshot_builds(
      snapshot, [],
      [common_pb2.SUCCESS, common_pb2.SCHEDULED, common_pb2.STARTED],
      patches=gerrit_changes)

  # Find number of builds, make set of builders, prioritize and log.
  initial_found_builds = len(snapshot_builds)
  snapshot_builds = prioritize_builds(api, snapshot_builds)
  filter_log.append(
      'from {} -> {} joinable after dedup and prioritization'.format(
          initial_found_builds, len(snapshot_builds)))

  completed_builders = [build.builder.builder for build in completed_builds]
  snapshot_build_targets = \
      api.cros_history.build_target_dict(snapshot_builds)

  filtered_snapshot_builds = []

  with api.step.nest('filter builds') as step:
    for child in child_builders:
      child_builder_config = api.cros_infra_config.get_builder_config(child)
      critical = child_builder_config.general.critical.value

      # now we have a list of build names such as ['buddy-postsubmit', ...]
      # whereas snapshot_builds and completed_builds might be postfixed
      # with -snapshot. Use this to filter out.
      # TODO(crbug/991996): Refactor: use something other than string manip.
      child_target = child[:child.rfind('-')]  # i.e. wizpig-snapshot -> wizpig
      # No need to retry previously-passed builds.
      if child in completed_builders:
        filter_log.append('{} already passed'.format(child_target))
        continue

      # Filter out builds not in the build plan.
      if child not in necessary_builders:
        filter_log.append('{} build is not needed for changes'.format(child))
        continue

      # We've already found an existing build, we'll just wait on it later.
      elif child_target in snapshot_build_targets:
        snapshot_build = snapshot_build_targets[child_target]
        snapshot_build.critical = common_pb2.YES if critical else common_pb2.NO
        filtered_snapshot_builds.append(snapshot_build)
        filter_log.append('{} exists, will join on it'.format(child_target))
        continue

      # Don't retry non-critical builds.
      if not critical and is_retry:
        filter_log.append(
            '{} is non-critical and this is a CQ rerun'.format(child))
        continue

      tags = api.cros_tags.make_schedule_tags(snapshot)

      # Technically per current approaches a bisecting orchestrator doing hw
      # test bisection should find all builds already completed or in flight
      # as *-snapshot builds. If it does need to schedule such a build, those
      # builders run in the postsubmit bucket.
      bucket = api.buildbucket.build.builder.bucket
      if bucket == 'bisect':
        bucket = 'postsubmit'

      # Don't use swarming_parent_run_id here yet, as child builder bots'
      # caches can be corrupted when their builds are canceled mid-sync.
      new_build_requests.append(
          api.buildbucket.schedule_request(
              gitiles_commit=snapshot, builder=child, bucket=bucket,
              gerrit_changes=gerrit_changes,
              critical=critical, properties=api.cq.props_for_child_build,
              tags=tags))
    step.presentation.logs['filter log'] = filter_log
    # Don't include irrelevant builder configs or snapshot builds in this
    # count for display, as they're mentioned in steps above.
    step.presentation.step_text = ('need {} new build{} (filtered {})'.format(
        len(new_build_requests), '' if len(new_build_requests) == 1 else 's',
        len(child_builders) - len(new_build_requests)))

  return completed_builds, filtered_snapshot_builds, new_build_requests


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
  with api.step.nest("get completed builds") as step:
    completed_builds = []
    passed_builds = api.cros_history.get_passed_builds()
    skip_log = []
    for build in passed_builds:
      # Filter out non-child builds like vm_test, dry run orchestrator or
      # hw_tests in the future.
      if build.builder.builder not in cq_orch_children:  #pragma: no cover
        continue

      builder_config = api.cros_infra_config.get_builder_config(
          build.builder.builder)
      # If the build ran before a known bug was fixed, don't reuse it.
      if build.start_time.seconds < builder_config.general.broken_before.seconds:
        skip_log.append('{} is skipped because it was broken till {}UTC'.format(
            build.builder.builder,
            datetime.utcfromtimestamp(
                builder_config.general.broken_before.seconds)))
        continue
      # Refresh the criticality of the builders.
      build.critical = (
          common_pb2.YES
          if builder_config.general.critical.value else common_pb2.NO)
      completed_builds.append(build)

    step.presentation.logs['skip log'] = skip_log
    return completed_builds


def validate_refs(refs):
  """Assert the given refs start with refs/heads.

  Args:
    refs (UpdateManifestRefs): Refs to validate.

  Raises:
    AssertionError: If any invalid ref is found.
  """
  validate_ref(refs.start, 'start')
  validate_ref(refs.build, 'build')
  validate_ref(refs.test, 'test')


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

  def toolchain_orchestrator_build_with_no_gitiles():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos',
                                             bucket='toolchain',
                                             builder='toolchain-orchestrator')
    build.input.gitiles_commit.Clear()
    return api.buildbucket.build(build)

  def cq_orchestrator_build_with_gerrit_change():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder='cq-orchestrator')
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return api.buildbucket.build(build)

  def bisecting_orchestrator_build():
    """Generate a test build proto for the bisecting orchestrator."""
    return api.buildbucket.ci_build(project='chromeos', bucket='bisect',
                                    builder='bisecting-orchestrator')

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
        gerrit_changes=[common_pb2.GerritChange(change=1234)],
        gitiles_commit=snapshot)

  vm_tests = [
      vm_test_build('vm-test'),
  ]

  moblab_vm_tests = [
      vm_test_build('moblab-vm-test'),
  ]

  cros_test_platforms = [
      build_pb2.Build(id=1234, builder={'builder': 'cros_test_platform'},
                      status=common_pb2.SUCCESS),
      build_pb2.Build(id=4321, builder={'builder': 'cros_test_platform'},
                      status=common_pb2.SUCCESS),
  ]
  ctp_response1 = rpc_pb2.BatchResponse(
      responses=[dict(schedule_build=cros_test_platforms[0])])
  ctp_response2 = rpc_pb2.BatchResponse(
      responses=[dict(schedule_build=cros_test_platforms[1])])

  hw_tests = [
      api.skylab.test_with_execute_response(id=1234),
      api.skylab.test_with_execute_response(id=4321),
  ]

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'arm-generic')),
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS, input=input_proto(
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

  yield (
      api.test('basic') + postsubmit_orchestrator_build() + #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect') +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
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
         api.buildbucket.simulated_search_results(
             builds, 'run builds.get build history.'
             'get completed builds.get change build history.'
             'buildbucket.search') +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('pointless_builds') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
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
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('join_if_inflight_orchs') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.properties(assert_singleton=True) +  #
         api.buildbucket.simulated_search_results(
             builds, step_name='find inflight orchestrator.'
             'find matching builds.buildbucket.search') +  #
         api.buildbucket.simulated_collect_output(
             builds, 'find inflight orchestrator.waiting for existing runs') +
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('runs_if_no_inflight_orchs') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
         api.properties(enable_history=True) +  #
         api.properties(assert_singleton=True) +  #
         api.buildbucket.simulated_search_results(
             [], step_name='find inflight orchestrator.'
             'find matching builds.buildbucket.search') +
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  yield (
      api.test('updates_refs') +  #
      postsubmit_orchestrator_build() +  #
      api.properties(update_manifest_refs={
          'start': 'refs/heads/foo',
          'success': 'refs/heads/bar'
      }) +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect') +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))

  yield (
      api.test('missing_gitiles_commit') +  #
      postsubmit_orchestrator_build_with_no_gitiles() +
      api.properties(update_manifest_refs={
          'start': 'refs/heads/foo',
          'success': 'refs/heads/bar'
      }) +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect') +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))

  yield (api.test('missing_gitiles_commit_with_defaults') +  #
         toolchain_orchestrator_build_with_no_gitiles() + #
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect') +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
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
             builds, step_name='run builds.get build history'
             '.find matching builds.buildbucket.search') + #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
             'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect') +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
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
          builds, step_name='run builds.collect') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect') +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
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
  yield (
      api.test('non-critical_child_builder_fails') +  #
      postsubmit_orchestrator_build() +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule') +  #
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule') +  #
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect') +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))

  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
  hw_tests = [
      api.skylab.test_with_execute_response(id=1234),
  ]

  builds = [
      api.buildbucket.ci_build_message(builder='amd64-generic-postsubmit',
                                       status='SUCCESS')
  ]
  api.cros_bisect.add_output_props(builds[0], 'amd64-generic')

  yield (api.test('with_test_bisection_invocation') +  #
         bisecting_orchestrator_build() +  #
         api.buildbucket.simulated_collect_output(
             builds, step_name='run builds.collect') +  #
         api.properties(
             **{
                 '$chromeos/cros_bisect':
                     CrosBisectProperties(
                         test={
                             'hw_test_failures': [{
                                 'test_spec':
                                     json_format.MessageToJson(hw_test_unit)
                             },],
                         })
             }) +  #
         api.buildbucket.simulated_schedule_output(
             ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
             'schedule kip.hw.bvt-cq.buildbucket.schedule') +  #
         api.buildbucket.simulated_collect_output(
             hw_tests, 'run tests.collect tests.'
             'collect skylab tasks.buildbucket.collect'))
