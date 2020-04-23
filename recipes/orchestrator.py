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
    'recipe_engine/step',
    'bot_cost',
    'build_plan',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_source',
    'cros_tags',
    'cros_test_proctor',
    'easy',
    'failures',
    'gerrit',
    'git',
    'git_footers',
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
from google.protobuf import wrappers_pb2

from collections import defaultdict
from datetime import datetime

import time

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  api.buildbucket.host = api.buildbucket.HOST_PROD_BEEFY

  push_manifest_refs = None
  with api.step.nest('set up orchestrator'):
    validate_refs(properties.update_manifest_refs)
    config = api.cros_infra_config.configure_builder(
        api.buildbucket.gitiles_commit,
        api.buildbucket.build.input.gerrit_changes)
    if not config:
      # No config found.  This was already logged, just exit.
      return

    api.cros_bisect.set_orchestrator_bisect_builder()
    snapshot = api.cros_infra_config.gitiles_commit
    gerrit_changes = api.cros_infra_config.gerrit_changes
    intern_snapshot_id = snapshot.id

    # clone internal manifest repo
    intern_repo_path = clone_repo(api, 'internal manifest',
        api.cros_source.INTERNAL_MANIFEST_URL, fetch=intern_snapshot_id
    )

    # read the Cr-External-Snapshot footer to get ref of external snapshot
    # that corresponds with the internal snapshot
    with api.context(cwd=intern_repo_path):
      footer_values = api.git_footers.from_ref(intern_snapshot_id,
          key='Cr-External-Snapshot'
      )

      # make sure we got exactly one snapshot ref
      assert footer_values and len(footer_values) == 1, \
          'expected exactly one Cr-External-Snapshot footer'
      extern_snapshot_id = footer_values[0]

    # clone the external manifest repo
    extern_repo_path = clone_repo(api, 'external manifest',
        api.cros_source.EXTERNAL_MANIFEST_URL, fetch=extern_snapshot_id
    )

    # create a helper function bound up to our exact repo url and path for
    # updating manifest snapshots refs internally and externally
    def _push_manifest_refs(ref):
      """Helper function to push the snapshot ref for both internal and
      external manifest repos to the given named ref.

      Args:
        ref (str): the ref to push to (possibly empty), or None
      """
      maybe_push_commit(api, 'manifest-internal',
          api.cros_source.INTERNAL_MANIFEST_URL, intern_repo_path,
          ref, intern_snapshot_id)
      maybe_push_commit(api, 'manifest',
          api.cros_source.EXTERNAL_MANIFEST_URL, extern_repo_path,
          ref, extern_snapshot_id)

    push_manifest_refs = _push_manifest_refs

  # Update the start ref to indicate we've begun processing the snapshot.
  push_manifest_refs(properties.update_manifest_refs.start)

  if gerrit_changes:
    api.gerrit.assert_changes_submittable(gerrit_changes)

  if properties.enable_history and gerrit_changes:
    if properties.assert_singleton:
      with api.step.nest('find inflight orchestrator') as presentation:
        older_running_builds = api.cros_history.get_matching_builds(
            api.buildbucket.build, statuses=[common_pb2.STARTED])

        # remove yourself potentially.
        older_running_builds = [
            b for b in older_running_builds if b.id != api.buildbucket.build.id
        ]

        # Is a run of the same configuration ongoing? If so, inform and join().
        if len(older_running_builds) > 0:
          presentation.step_text = 'found {} inflight run(s) to wait on'\
                                        .format(len(older_running_builds))

          # Give the UI the links to STARTED builds with same configuration.
          for build in older_running_builds:
            title = api.naming.get_build_title(build)
            url = api.buildbucket.build_url(build_id=build.id)
            presentation.links[title] = url

          # Wait for all started builds.
          api.buildbucket.collect_builds(
              [b.id for b in older_running_builds],
              step_name='waiting for existing runs',
              timeout=60 * 60 * 23,
          )
        else:
          presentation.step_text = 'found no inflight run'

  child_specs = []
  with api.step.nest('run builds') as presentation:
    child_specs = get_child_specs(api)
    completed_builds = filter_schedule_wait_builds(
        api, presentation, child_specs, properties.enable_history,
        snapshot, gerrit_changes,
        stagger_children_seconds=properties.stagger_children_seconds)

  # From here all builds should have been collected: move to checking results.
  with api.step.nest('check build results') as presentation:
    for build in completed_builds:
      if build.status in (common_pb2.STARTED, common_pb2.SCHEDULED):
        presentation.text = 'some builds are running/pending'
    relevant_builds = []
    for build in completed_builds:
      # Assume relevant if the child doesn't have the relevant_build prop.
      if ('relevant_build' not in build.output.properties or
          build.output.properties['relevant_build']):
        relevant_builds.append(build.builder.builder)
    presentation.logs['relevant_builds'] = \
        sorted(relevant_builds or ['no relevant builds'])
    failures = api.failures.get_build_failures(completed_builds)

  # Recheck the BuilderConfigs at HEAD to see if any failed builds are now
  # non-critical. Snapshot builds are always scheduled without the critical bit
  # set to `NO` so this is also the only place that we will discover that.
  with api.step.nest('non-critical build check') as presentation:
    api.cros_infra_config.force_reload()
    child_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        presentation, failures, child_builder_configs)
  fatal_failures = [f for f in failures if f.fatal == True]

  if not fatal_failures:
    # If we've made it this far, the child builders were successful
    # and we can update the build success manifest ref if it is specified.
    push_manifest_refs(properties.update_manifest_refs.build)

  # If this is a dry run, check that the builds passed and quit.
  if not properties.enable_tests_on_dry_runs and api.cq.state == api.cq.DRY:
    return api.failures.aggregate_failures(failures)

  # Otherwise, run tests for builds that weren't build failures and that
  # still exist as builders.
  need_tests_builds = [
      b for b in completed_builds if b.status == common_pb2.SUCCESS and
      child_builder_configs.get(b.builder.builder)
  ]

  # Is the build tagged as overriding the PCQ quota scheduler account?
  if api.cros_tags.has_entry('cq_cl_tag', 'pupr:chromeos-base/chromeos-chrome',
                             api.buildbucket.build.tags):
    api.skylab.set_qs_account('pupr')

  test_failures = api.cros_test_proctor.run_proctor(
      need_tests_builds, snapshot, gerrit_changes, properties.enable_history)
  failures.extend(test_failures)

  # Victory! If we've made it this far, all tests were successful
  # and we can update the test success manifest ref if it is specified.
  push_manifest_refs(properties.update_manifest_refs.test)

  # Launch any specified follow on orchestrator.
  if not fatal_failures and config.orchestrator.follow_on_orchestrator.name:
    with api.step.nest('run follow on orchestrator') as presentation:
      completed_builds.extend(schedule_wait_follow_on(
          api, presentation, config, properties.enable_history, snapshot,
          gerrit_changes))

  with api.step.nest('clean up orchestrator') as presentation:
    api.bot_cost.calculate_cq_run_cost(api.buildbucket.build.id,
                                       completed_builds, presentation)

    # Recheck the BuilderConfigs at HEAD, one last time, to see if any failed
    # builders are now noncritical.
    api.cros_infra_config.force_reload()
    child_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        presentation, failures, child_builder_configs)
  return api.failures.aggregate_failures(failures)


def clone_repo(api, name, url, fetch=None):
  """Clone a repo into a temporary directory.

  Args:
    api   (RecipeApi): See RunSteps documentation.
    name  (str):       Name of repo for display purposes
    url   (str):       Url to clone from
    fetch (str|None):  If specified, ref to fetch from remote

  Returns:
    path (Path): path on disk to cloned repo
  """
  path = api.path.mkdtemp()
  with api.step.nest('clone %s repo' % name), api.context(cwd=path):
    api.git.clone(url, timeout_sec=60 * 60)
    if fetch:
      api.git.fetch_ref(url, fetch, timeout_sec= 60 * 60)
  return path


def schedule_wait_follow_on(api, parent_step, config,
                            enable_history, snapshot, gerrit_changes):
  """Run and collect any followon orchestrator.

  Args:
    api (RecipeApi): See RunSteps documentation.
    parent_step (Step): the calling step, to be used for presentation purposes.
    config (BuilderConfig): the config for this orchestrator.
    enable_history (bool): Enables history lookup in cq orchestrator.
    snapshot (GitilesCommit): Start ref to be supplied to the child builds.
    gerrit_changes list(GerritChange): List of patches in the order that they
      can be cherry-picked.

  Returns: A list of build_pb2.Build objects with results.
  """
  completed_builds = []
  follow_on = config.orchestrator.follow_on_orchestrator

  # Schedule the follow on orchestrator.
  tags = api.cros_tags.make_schedule_tags(snapshot)
  # The follow on orchestrator may or may not be in the same bucket as us, and
  # the gitiles_commit and gerrit_changes that we are using may have derived
  # from our builder config, rather than buildbucket properties.  Pass the
  # actual answers to schedule_request.
  # Pass in empty properties until we determine that we need some.
  bucket = api.buildbucket.build.builder.bucket
  properties = api.cros_infra_config.props_for_child_build
  req = api.buildbucket.schedule_request(
      gitiles_commit=snapshot, builder=follow_on.name, bucket=bucket,
      gerrit_changes=gerrit_changes, critical=True, properties=properties,
      tags=tags)
  title_fn = api.naming.get_build_title
  [build] = api.buildbucket.schedule([req], url_title_fn=title_fn)
  url = api.buildbucket.build_url(build_id=build.id)
  parent_step.presentation.links[title_fn(build)] = url

  # Are we supposed to wait?
  if follow_on.await_completion:
    fields = api.buildbucket.DEFAULT_FIELDS | {'tags'}
    try:
      completed_builds += api.buildbucket.collect_builds(
          [build.id], timeout=60 * 60 * 36, step_name='collect',
          url_title_fn=title_fn, fields=fields).values()
    except api.step.StepFailure:  #pragma: no cover
      completed_builds += api.buildbucket.get_multi([build.id], step_name='get',
                                                    url_title_fn=title_fn,
                                                    fields=fields).values()

  return completed_builds

def get_child_specs(api):
  """Returns the child specs that should be run for this invocation.

  Args:
    api (RecipeApi): See RunSteps.

  Returns:
    list[ChildSpec] of children to run
  """
  child_builders = api.cros_bisect.get_test_child_builders()
  if child_builders:
    return [BuilderConfig.Orchestrator.ChildSpec(
        name = cb,
        collect_handling = BuilderConfig.Orchestrator.ChildSpec.COLLECT,
    ) for cb in child_builders]
  return api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder).orchestrator.child_specs


def filter_schedule_wait_builds(api, parent_step, child_specs,
                                enable_history, snapshot, gerrit_changes,
                                stagger_children_seconds=0.0):
  """Find the builds you need, filter those already started, run, and collect.

  Most of the heavy lifting is done in get_build_plan.

  Args:
    api (RecipeApi): See RunSteps documentation.
    parent_step (Step): the calling step, to be used for presentation purposes.
    child_specs (list(ChildSpec)): A list of child specs.
    enable_history (bool): Enables history lookup in cq orchestrator.
    snapshot (GitilesCommit): Start ref to be supplied to the child builds.
    gerrit_changes list(GerritChange): List of patches in the order that they
      can be cherry-picked.
    stagger_children_seconds (float): The number of seconds between each child
      build's start (until crbug.com/1063143).

  Returns: A list of build_pb2.Build objects with build results.
  """
  completed_builds, existing_builds, new_build_requests = api.build_plan.get_build_plan(
      child_specs=child_specs, enable_history=enable_history,
      gerrit_changes=gerrit_changes, snapshot=snapshot)
  parent_step.presentation.step_text = ('{} new, {} recycled'.format(
      len(new_build_requests),
      len(completed_builds) + len(existing_builds)))

  if new_build_requests:
    # Implement sleepy builds for GoB smoothing: crbug.com/1063143
    with api.step.nest('schedule new builds') as pres:
      with api.buildbucket.with_host(api.buildbucket.HOST_PROD):
        for new_build_request in new_build_requests:
            # request new builds and add to total existing.
            existing_builds += api.buildbucket.schedule(
                [new_build_request], url_title_fn=api.naming.get_build_title)
            time.sleep(stagger_children_seconds)

  child_specs_dict = {cs.name:cs for cs in child_specs}
  child_targets_dict = {cs.name[:cs.name.rfind('-')]:cs for cs in child_specs}
  collect_builds = [b for b in existing_builds
                    if should_collect(b, child_specs_dict, child_targets_dict)]

  # collect all existing builds, add to completed builds
  fields = api.buildbucket.DEFAULT_FIELDS | {'tags'}
  try:
    completed_builds += api.buildbucket.collect_builds(
        [b.id for b in collect_builds], timeout=60 * 60 * 36,
        step_name='collect', url_title_fn=api.naming.get_build_title,
        fields=fields).values()
  except api.step.StepFailure:  #pragma: no cover
    completed_builds += api.buildbucket.get_multi(
        [b.id for b in collect_builds], step_name='get',
        url_title_fn=api.naming.get_build_title, fields=fields).values()

  return completed_builds


def should_collect(build, child_specs_dict, child_targets_dict):
  """Returns whether the orchestrator should collect the build.

  Args:
    build (build_pb2.Build): the build to check whether to collect.
    child_specs_dict (dict): mapping of builder name to ChildSpec.
    child_targets_dict (dict): fuzzy mapping of builder target to to ChildSpec.
      Fuzzy in the sense that it just chops off from the last '-' to the end
      of the string. Intended to pick up the *-snapshot cases. See more below.

  Returns: A bool whether to collect the build.
  """
  builder_name = build.builder.builder
  child_spec = child_specs_dict.get(builder_name)
  if not child_spec:  #pragma: no cover
    # Missed lookup, the existing build name was not a name in child_specs.
    # The usual case would be existing build has a *-snapshot name but the
    # orchestrator's child has a *-postsubmit name.
    # TODO(crbug/991996): Refactor: use something other than string manip.
    child_spec = child_targets_dict.get(builder_name[:builder_name.rfind('-')])
  if not child_spec:  #pragma: no cover
    # Missed lookup even after fallback for *-snapshot.
    return True
  return (child_spec.collect_handling
          != BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT)


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


def maybe_push_commit(api, repo_name, repo_url, repo_path, ref, commit):
  """Update a ref in the remote repo to point to a given commit.  If ref
  evaluates as False, then do nothing

  Args:
    api (RecipeApi):  See RunSteps documentation.
    repo_name (str):  Name of repo for display purposes
    repo_url  (str):  URL of remote repo to push to
    repo_path (Path): Path to local repo to push from
    ref       (str):  ref to push to (possibly empty) or None
    commit    (str):  commit SHA1 to push to ref
  """
  if ref:
    with api.context(cwd=repo_path):
      with api.step.nest('update %s ref %s' % (repo_name, ref)):
        api.git.push(repo_url, "%s:%s" % (commit, ref))


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

  def orderfile_generate_orchestrator():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(
        project='chromeos', bucket='toolchain',
        builder='orderfile-generate-orchestrator')
    return api.buildbucket.build(build)

  def toolchain_orchestrator_build(gitiles=True, changes=False):
    """Generate a test build proto for toolchain builders"""
    build = api.buildbucket.ci_build_message(project='chromeos',
                                             bucket='toolchain',
                                             builder='toolchain-orchestrator')
    if not gitiles:
      build.input.gitiles_commit.Clear()
    if changes:
      build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return api.buildbucket.build(build)

  def cq_orchestrator_build_with_gerrit_change(tags=None):
    """Generate a test build proto with gerrit changes."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder='cq-orchestrator',
                                             tags=tags)
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
      api.skylab.test_with_execute_response_json(id=1234),
      api.skylab.test_with_execute_response_json(id=4321),
  ]

  output = build_pb2.Build.Output()
  output.properties['build_cost'] = 10.0

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
          'builder': 'amd64-generic-snapshot'
      }, status=common_pb2.STARTED, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514003, builder={
          'builder': 'amd64-generic-snapshot'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514005, builder={
          'builder': 'amd64-generic-snapshot'
      }, status=common_pb2.SUCCESS,
                      input=dict(properties=struct_pb2.Struct())),  # no bt
      build_pb2.Build(id=8922054662172514004, builder={
          'builder': 'amd64-generic-snapshot'
      }, status=common_pb2.SCHEDULED, input=input_proto(None, 'amd64-generic')),
  ]

  followon_resp1 = rpc_pb2.BatchResponse(
      responses=[dict(schedule_build=build_pb2.Build(
          id=5555, builder={'builder': 'orderfile-verify-orchestrator'},
          status=common_pb2.SUCCESS))])

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

  yield (api.test('no_config') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='no-such'))

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
         postsubmit_orchestrator_build() +  #
         # api.cq(full_run=True) +  #
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

  yield (api.test('orchestrator_with_follow_on') +  #
         orderfile_generate_orchestrator() + #
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
          step_name='run tests.collect tests.collect moblab vm tests') + #
      api.buildbucket.simulated_schedule_output(
          followon_resp1, 'run follow on orchestrator.buildbucket.schedule'))

  yield (api.test('missing_gitiles_commit_with_defaults') +  #
         toolchain_orchestrator_build(gitiles=False) + #
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

  yield (api.test('missing_gitiles_commit_with_changes') +  #
         toolchain_orchestrator_build(gitiles=False, changes=True) + #
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

  yield (api.test('quota_scheduler_override') +  #
         cq_orchestrator_build_with_gerrit_change(
             tags=[common_pb2.StringPair(
                 key='cq_cl_tag',
                 value='pupr:chromeos-base/chromeos-chrome')]) +  #
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
      api.skylab.test_with_execute_response_json(id=1234),
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
