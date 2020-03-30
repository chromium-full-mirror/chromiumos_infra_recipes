# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that generates artifacts using HW Test results.

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
    'failures',
    'gerrit',
    'git',
    'git_footers',
    'naming',
    'skylab',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.recipes.chromeos.afdo_orchestrator import AfdoOrchestratorProperties

PROPERTIES = AfdoOrchestratorProperties

# TODO(crbug/1053703): refactor this along with orchestrator.py
# Most of this builder will be greatly simplified as part of refactoring
# orchestrator.py into a menu module.  Any functions that look similar to those
# in orchestrator.py are expected migrate to a recipe module.


def RunSteps(api, properties):
  api.buildbucket.host = api.buildbucket.HOST_PROD_BEEFY

  push_manifest_refs = None
  with api.step.nest('set up orchestrator'):
    config = api.cros_infra_config.configure_builder(
        api.buildbucket.gitiles_commit,
        api.buildbucket.build.input.gerrit_changes)
    if not config:
      # No config found.  This was already logged, just exit.
      return

    api.cros_bisect.set_orchestrator_bisect_builder()
    snapshot = api.cros_infra_config.gitiles_commit
    gerrit_changes = api.cros_infra_config.gerrit_changes

  # This orchestrator ignores the config, using enable_history=True
  if gerrit_changes:
    api.gerrit.assert_changes_submittable(gerrit_changes)
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
        api, presentation, child_specs, True, snapshot, gerrit_changes)

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
    presentation.logs['relevant_builds'] = sorted(relevant_builds)
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

  # If this is a dry run, check that the builds passed and quit.
  # TODO(crbug/1071440): Because the HW Tests have production side effects, we
  # need to not run them for dryruns at this time.
  if api.cq.state == api.cq.DRY:
    return api.failures.aggregate_failures(failures)

  # Otherwise, run tests for builds that weren't build failures and that
  # still exist as builders.
  need_tests_builds = [
      b for b in completed_builds if b.status == common_pb2.SUCCESS and
      child_builder_configs.get(b.builder.builder)
  ]

  test_failures = api.cros_test_proctor.run_proctor(
      need_tests_builds, snapshot, gerrit_changes, True)
  failures.extend(test_failures)

  # Create InputArtifactInfo for the CHROME_DEBUG_BINARY from the creating
  # builder.
  property_art = lambda b: b.output.properties['artifacts']
  locs = list(
      set('{}/{}'.format(
          property_art(b)['gs_bucket'],
          property_art(b)['gs_path'])
          for b in need_tests_builds
          if property_art(b)['gs_bucket']))
  input_artifacts = [
      dict(input_artifact_type=BuilderConfig.Artifacts.CHROME_DEBUG_BINARY,
           input_artifact_gs_locations=locs)
  ]

  # Schedule and wait for any process_child builder.
  if not fatal_failures and properties.process_child:
    with api.step.nest('run {}'.format(properties.process_child)) as pres:
      processed = schedule_wait_process_child(
          api, pres, properties.process_child, input_artifacts, snapshot,
          gerrit_changes)
      completed_builds.extend(processed)
      # Update the failure variables.
      process_failures = api.failures.get_build_failures(processed)
      failures.extend(process_failures)
      fatal_failures.extend([f for f in process_failures if f.fatal == True])

  # Launch any specified follow on orchestrator.
  if not fatal_failures and config.orchestrator.follow_on_orchestrator.name:
    with api.step.nest('run follow on orchestrator') as presentation:
      completed_builds.extend(schedule_wait_follow_on(
          api, presentation, config, True, snapshot, gerrit_changes))

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


# TODO(crbug/1053703): This and schedule_wait_follow_on should be merged.
def schedule_wait_process_child(
    api, parent_step, name, input_artifacts, snapshot, gerrit_changes):
  """Run and collect any process_child.

  Args:
    api (RecipeApi): See RunSteps documentation.
    parent_step (Step): the calling step, to be used for presentation purposes.
    name (str): The name of the child builder.
    input_artifacts (list[InputArtifactInfo]): List of input artifacts to pass.
    snapshot (GitilesCommit): Start ref to be supplied to the child builds.
    gerrit_changes list(GerritChange): List of patches in the order that they
      can be cherry-picked.

  Returns: A list of (one) build_pb2.Build object with the process_child result.
  """
  completed_builds = []

  # Schedule the follow on orchestrator.
  tags = api.cros_tags.make_schedule_tags(snapshot)
  # The follow on orchestrator may or may not be in the same bucket as us, and
  # the gitiles_commit and gerrit_changes that we are using may have derived
  # from our builder config, rather than buildbucket properties.  Pass the
  # actual answers to schedule_request.
  # Pass in empty properties until we determine that we need some.
  bucket = api.buildbucket.build.builder.bucket
  properties = api.cros_infra_config.props_for_child_build
  properties.update({'input_artifacts': input_artifacts})
  req = api.buildbucket.schedule_request(
      gitiles_commit=snapshot, builder=name, bucket=bucket,
      gerrit_changes=gerrit_changes, critical=True, properties=properties,
      tags=tags)
  title_fn = api.naming.get_build_title
  [build] = api.buildbucket.schedule([req], url_title_fn=title_fn)
  url = api.buildbucket.build_url(build_id=build.id)
  parent_step.presentation.links[title_fn(build)] = url

  fields = api.buildbucket.DEFAULT_FIELDS | {'tags'}
  try:
    completed_builds += api.buildbucket.collect_builds(
        [build.id], timeout=60 * 60 * 4, step_name='collect',
        url_title_fn=title_fn, fields=fields).values()
  except api.step.StepFailure:  #pragma: no cover
    completed_builds += api.buildbucket.get_multi([build.id], step_name='get',
                                                  url_title_fn=title_fn,
                                                  fields=fields).values()

  return completed_builds


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
  return api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder).orchestrator.child_specs


def filter_schedule_wait_builds(api, parent_step, child_specs,
                                enable_history, snapshot, gerrit_changes):
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

  Returns: A list of build_pb2.Build objects with build results.
  """
  completed_builds, existing_builds, new_build_requests = \
      api.build_plan.get_build_plan(
      child_specs=child_specs, enable_history=enable_history,
      gerrit_changes=gerrit_changes, snapshot=snapshot)
  parent_step.presentation.step_text = ('{} new, {} recycled'.format(
      len(new_build_requests),
      len(completed_builds) + len(existing_builds)))

  # request new builds and add to total existing.
  existing_builds += api.buildbucket.schedule(
      new_build_requests, url_title_fn=api.naming.get_build_title)

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


def GenTests(api):

  def postsubmit_orchestrator_build():
    """Generate a test build proto for the postsubmit orchestrator."""
    return api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                    builder='postsubmit-orchestrator')

  def orderfile_generate_orchestrator():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(
        project='chromeos', bucket='toolchain',
        builder='orderfile-generate-orchestrator')
    return api.buildbucket.build(build)

  def cq_orchestrator_build_with_gerrit_change(tags=None):
    """Generate a test build proto with gerrit changes."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder='cq-orchestrator',
                                             tags=tags)
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
  output.properties['artifacts'] = {
      'gs_bucket': 'chromeos-image-archive',
      'gs_path': 'BUILDER/VERSION-BUILD_ID'}

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic'),
                      output=output),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'arm-generic'),
                      output=output),
  ]

  process_resp1 = rpc_pb2.BatchResponse(responses=[
      dict(
          schedule_build=build_pb2.Build(
              id=5555, builder={'builder':
                  'PROCESS'}, status=common_pb2.SUCCESS))
  ])

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

  yield (api.test('join_if_inflight_orchs') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(full_run=True) +  #
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

  yield (api.test('dry_run') +  #
         cq_orchestrator_build_with_gerrit_change() +  #
         api.cq(dry_run=True))

  yield (api.test('quota_scheduler_override') +  #
         cq_orchestrator_build_with_gerrit_change(
             tags=[common_pb2.StringPair(
                 key='cq_cl_tag',
                 value='pupr:chromeos-base/chromeos-chrome')]) +  #
         api.cq(full_run=True) +  #
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

  yield (api.test('orchestrator_with_process_child_and_followon') +  #
         orderfile_generate_orchestrator() +  #
         api.properties(process_child='PROCESS') +  #
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
             step_name='run tests.collect tests.collect moblab vm tests') +  #
         api.buildbucket.simulated_schedule_output(
             process_resp1, 'run PROCESS.buildbucket.schedule') +  #
         api.buildbucket.simulated_schedule_output(
             followon_resp1, 'run follow on orchestrator.buildbucket.schedule'))
