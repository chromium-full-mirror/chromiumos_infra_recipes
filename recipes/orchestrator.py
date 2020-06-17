# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'build_plan',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'cros_test_proctor',
    'failures',
    'gerrit',
    'naming',
    'orch_menu',
    'skylab',
    'test_util',
]

from PB.chromite.api.test import VmTestRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.recipes.chromeos.build_target import BuildTargetProperties
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
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api, properties, config)


def DoRunSteps(api, properties, config):
  # Update the start ref to indicate we've begun processing the snapshot.
  api.orch_menu.push_manifest_refs(properties.update_manifest_refs.start)

  snapshot = api.orch_menu.gitiles_commit
  gerrit_changes = api.orch_menu.gerrit_changes
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
        api, presentation, child_specs, properties.enable_history, snapshot,
        gerrit_changes,
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
    api.orch_menu.push_manifest_refs(properties.update_manifest_refs.build)

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

  test_failures = api.cros_test_proctor.run_proctor(need_tests_builds, snapshot,
                                                    gerrit_changes,
                                                    properties.enable_history)
  failures.extend(test_failures)

  # Victory! If we've made it this far, all tests were successful
  # and we can update the test success manifest ref if it is specified.
  api.orch_menu.push_manifest_refs(properties.update_manifest_refs.test)

  # Launch any specified follow on orchestrator.
  if not fatal_failures and config.orchestrator.follow_on_orchestrator.name:
    with api.step.nest('run follow on orchestrator') as presentation:
      completed_builds.extend(
          schedule_wait_follow_on(api, presentation, config,
                                  properties.enable_history, snapshot,
                                  gerrit_changes))

  with api.step.nest('clean up orchestrator') as presentation:
    api.bot_cost.set_cq_run_cost(completed_builds)

    # Recheck the BuilderConfigs at HEAD, one last time, to see if any failed
    # builders are now noncritical.
    api.cros_infra_config.force_reload()
    child_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        presentation, failures, child_builder_configs)
  return api.failures.aggregate_failures(failures)


def schedule_wait_follow_on(api, parent_step, config, enable_history, snapshot,
                            gerrit_changes):
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

  # Separate out any project/bucket in the builder name.
  parts = follow_on.name.split('/', 2)
  project = api.buildbucket.INHERIT if len(parts) < 3 else parts[-3]
  bucket = api.buildbucket.INHERIT if len(parts) < 2 else parts[-2]
  builder = parts[-1]

  # Schedule the follow on orchestrator.
  tags = api.cros_tags.make_schedule_tags(snapshot)
  # The follow on orchestrator may or may not be in the same bucket as us, and
  # the gitiles_commit and gerrit_changes that we are using may have derived
  # from our builder config, rather than buildbucket properties.  Pass the
  # actual answers to schedule_request.
  # Pass in empty properties until we determine that we need some.
  properties = api.cros_infra_config.props_for_child_build
  req = api.buildbucket.schedule_request(gitiles_commit=snapshot,
                                         project=project, bucket=bucket,
                                         builder=builder,
                                         gerrit_changes=gerrit_changes,
                                         critical=True, properties=properties,
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
    return [
        BuilderConfig.Orchestrator.ChildSpec(
            name=cb,
            collect_handling=BuilderConfig.Orchestrator.ChildSpec.COLLECT,
        ) for cb in child_builders
    ]
  return api.cros_infra_config.config.orchestrator.child_specs


def filter_schedule_wait_builds(api, parent_step, child_specs, enable_history,
                                snapshot, gerrit_changes,
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

  child_specs_dict = {cs.name: cs for cs in child_specs}
  child_targets_dict = {cs.name[:cs.name.rfind('-')]: cs for cs in child_specs}
  collect_builds = [
      b for b in existing_builds
      if should_collect(b, child_specs_dict, child_targets_dict)
  ]

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
  return (child_spec.collect_handling !=
          BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT)


def GenTests(api):

  def test_orchestrator(cq=False, **kwargs):
    """Generate a test build proto for the postsubmit orchestrator."""
    if not cq:
      kwargs.setdefault(
          'input_properties',
          OrchestratorProperties(
              update_manifest_refs=dict(build='refs/heads/stable',
                                        start='refs/heads/postsubmit')))
    return api.test_util.test_orchestrator(cq=cq, **kwargs).build

  def vm_test_build(name):
    # The only things we care about are output.properties.name and status.
    return json_format.ParseDict(
        dict(
            output=dict(properties=dict(name=name)), status=common_pb2.SUCCESS),
        build_pb2.Build())

  vm_tests = [vm_test_build('vm-test')]

  moblab_vm_tests = [vm_test_build('moblab-vm-test')]

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

  builds = [
      api.test_util.test_child_build(
          'amd64-generic', cq=True, build_id=8922054662172514000,
          status='SUCCESS', output_properties=dict(build_cost=10.0)).message,
      api.test_util.test_child_build('arm-generic', cq=True,
                                     build_id=8922054662172514001,
                                     status='STARTED').message,
      api.test_util.test_child_build('atlas', cq=True,
                                     build_id=8922054662172514002,
                                     start_time=1562475245, status='SUCCESS',
                                     revision=None).message,
  ]

  # we have three here to properly exercise "prioritize_builds"
  existing_annealing_builds = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514002,
                                     bucket='snapshot',
                                     status='STARTED').message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514003,
                                     bucket='snapshot',
                                     status='SUCCESS').message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514005,
                                     bucket='snapshot',
                                     status='SUCCESS').message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514004,
                                     bucket='snapshot',
                                     status='SCHEDULED').message,
  ]

  followon_resp1 = rpc_pb2.BatchResponse(responses=[
      dict(
          schedule_build=api.test_util.test_orchestrator(
              build_id=5555, bucket='toolchain',
              builder='orderfile-verify-orchestrator',
              status='SUCCESS').message,
      )
  ])

  yield api.test(
      'basic',
      test_orchestrator(),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test('no_config', test_orchestrator(builder='no-such'))

  yield api.test(
      'fails_if_changes_not_submittable',
      test_orchestrator(cq=True),
      api.gerrit.simulated_changes_are_submittable(submittable=False),
  )

  yield api.test(
      'builds_with_history',
      test_orchestrator(
          cq=True,
          input_properties=OrchestratorProperties(enable_history=True)),
      api.buildbucket.simulated_search_results(
          builds, 'run builds.get build history.'
          'get completed builds.get change build history.'
          'buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'pointless_builds',
      test_orchestrator(
          cq=True,
          input_properties=OrchestratorProperties(enable_history=True)),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'joinable_existing_annealing_builds',
      test_orchestrator(
          input_properties=OrchestratorProperties(enable_history=True)),
      api.buildbucket.simulated_search_results(
          existing_annealing_builds, 'run builds.get snapshot builds'
          '.buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'join_if_inflight_orchs',
      test_orchestrator(
          cq=True,
          input_properties=OrchestratorProperties(enable_history=True,
                                                  assert_singleton=True)),
      api.buildbucket.simulated_search_results(
          builds, step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          builds, 'find inflight orchestrator.waiting for existing runs'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'runs_if_no_inflight_orchs',
      test_orchestrator(
          cq=True,
          input_properties=OrchestratorProperties(enable_history=True,
                                                  assert_singleton=True)),
      api.buildbucket.simulated_search_results(
          [], step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'updates_refs',
      test_orchestrator(
          input_properties=OrchestratorProperties(update_manifest_refs={
              'start': 'refs/heads/foo',
              'build': 'refs/heads/bar'
          })),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'missing_gitiles_commit',
      test_orchestrator(
          revision=None,
          input_properties=OrchestratorProperties(update_manifest_refs={
              'start': 'refs/heads/foo',
              'build': 'refs/heads/bar'
          })),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'orchestrator_with_follow_on',
      test_orchestrator(bucket='toolchain',
                        builder='orderfile-generate-orchestrator'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
      api.buildbucket.simulated_schedule_output(
          followon_resp1, 'run follow on orchestrator.buildbucket.schedule'),
  )

  yield api.test(
      'missing_gitiles_commit_with_defaults',
      test_orchestrator(revision=None),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test(
      'missing_gitiles_commit_with_changes',
      test_orchestrator(revision=None, cq=True),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  yield api.test('dry_run', test_orchestrator(cq=True, dry_run=True))

  yield api.test(
      'quota_scheduler_override',
      test_orchestrator(
          cq=True, input_properties=OrchestratorProperties(enable_history=True),
          tags=api.cros_tags.tags(
              cq_cl_tag='pupr:chromeos-base/chromeos-chrome')),
      api.buildbucket.simulated_search_results(
          builds, 'run builds.get build history.'
          'get completed builds.get change build history.'
          'buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  builds = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514000,
                                     status='FAILURE',
                                     critical=common_pb2.NO).message,
      api.test_util.test_child_build('arm-generic',
                                     build_id=8922054662172514001,
                                     status='SUCCESS',
                                     critical=common_pb2.NO).message,
  ]

  yield api.test(
      'retry_only_critical_builds',
      test_orchestrator(
          cq=True,
          input_properties=OrchestratorProperties(enable_history=True)),
      api.buildbucket.simulated_search_results(
          builds, step_name='run builds.get build history'
          '.find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  builds = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514000,
                                     status='FAILURE',
                                     critical=common_pb2.YES).message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514001,
                                     status='SUCCESS',
                                     critical=common_pb2.NO).message,
  ]
  yield api.test(
      'critical_child_builder_fails',
      test_orchestrator(),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  builds = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514000,
                                     status='SUCCESS',
                                     critical=common_pb2.YES).message,
      api.test_util.test_child_build('arm-generic',
                                     build_id=8922054662172514001,
                                     status='FAILURE',
                                     critical=common_pb2.NO).message,
  ]
  yield api.test(
      'non-critical_child_builder_fails',
      test_orchestrator(),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'),
  )

  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
  hw_tests = [
      api.skylab.test_with_execute_response_json(id=1234),
  ]

  builds = [
      api.test_util.test_child_build('amd64-generic', status='SUCCESS').message
  ]
  api.cros_bisect.add_output_props(builds[0], 'amd64-generic')

  yield api.test(
      'with_test_bisection_invocation',
      test_orchestrator(bucket='bisect', builder='bisecting-orchestrator'),
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
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
          }),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule kip.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
  )
