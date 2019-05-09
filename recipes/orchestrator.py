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
    'cros_history',
    'cros_infra_config',
    'cros_source',
    'cros_version',
    'failures',
    'git',
    'gitiles',
    'naming',
    'test_plan',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2
from recipe_engine.config import ConfigGroup
from recipe_engine.config import Single
from recipe_engine.recipe_api import DeferredResult
from recipe_engine.recipe_api import Property

PROPERTIES = {
    # Specifies which refs in the manifest repository should point to the
    # snapshot ref used by the orchestrator, and when.
    'update_manifest_refs':
        Property(
            kind=ConfigGroup(
                # The start ref is updated before child builds are launched.
                # An example start ref is 'postsubmit', which should update
                # right when the orchestrator launches.
                start=Single(str),

                # The success ref is updated only if all child builds succeed.
                # An example success ref is 'stable', which should update only
                # when postsubmit builds succeed.
                success=Single(str),
            ),
            default={},
        ),
    # Specifies whether to enable cros_history based resource saving.
    'enable_history':
        Property(kind=bool, default=True),
}


def RunSteps(api, update_manifest_refs, enable_history):
  validate_refs(update_manifest_refs.values())

  manifest_commit = api.buildbucket.gitiles_commit
  if not manifest_commit.project:
    manifest_commit = _load_manifest_commit_from_snapshot(api)

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    # Point start ref to the input snapshot if specified.
    maybe_update_manifest_ref(api, update_manifest_refs, 'start')

    requests = []
    completed_builds = []
    passed_builders = set()
    tested_targets = set()

    orchestrator_builder_config = api.cros_infra_config.get_builder_config(
        api.buildbucket.build.builder.builder)
    if enable_history and api.buildbucket.build.input.gerrit_changes:
      completed_builds = api.cros_history.passed_builds(
          api.buildbucket.build.input.gerrit_changes)
      tested_targets = api.cros_history.passed_targets(
          api.buildbucket.build.input.gerrit_changes)
      passed_builders = set(build.builder.builder for build in completed_builds)
    for child in orchestrator_builder_config.orchestrator.children:
      if child not in passed_builders:
        child_builder_config = api.cros_infra_config.get_builder_config(child)
        requests.append(
            api.buildbucket.schedule_request(
                gitiles_commit=manifest_commit,
                builder=child,
                critical=child_builder_config.general.critical.value))

    completed_builds += api.buildbucket.run(
        requests, timeout=60 * 60 * 4, step_name='run child builds',
        url_title_fn=api.naming.get_build_title)
    # Defer exceptions until the end, so that we recover gracefully
    # from intermediate failures.
    with api.step.defer_results():
      api.failures.verify_builds(completed_builds)
      if api.buildbucket.build.input.gerrit_changes:
        untested_builds = _get_untested_builds(api, completed_builds,
                                               tested_targets)
      else:
        untested_builds = completed_builds

      if not api.cq.state == api.cq.DRY:
        test_results = run_tests(api, untested_builds)
        api.failures.verify_tests(test_results)

    # Victory! If we've made it this far, the child builders were successful
    # and we can update the success manifest ref if it is specified.
    maybe_update_manifest_ref(api, update_manifest_refs, 'success')


def _load_manifest_commit_from_snapshot(api):
  """Fetches latest manifest snapshot commit from Gitiles.

  Args:
    api (object): See RunSteps documentation.

  Returns:
    common_pb2.GitilesCommit
  """
  with api.step.nest('fetch manifest ref'):
    rev = api.gitiles.fetch_revision(
        'chrome-internal', 'chromeos/manifest-internal', 'snapshot')
    return common_pb2.GitilesCommit(
        host='chrome-internal.googlesource.com',
        project='chromeos/manifest-internal',
        ref='refs/heads/snapshot',
        id=rev)


def _get_untested_builds(api, completed_builds, tested_targets):
  """Get `completed_builds` that aren't in `tested_targets`.

  Args:
    api (object): See RunSteps documentation.
    completed_builds (list[build_pb2.Build]): Completed builds returned from
      Buildbucket.
    tested_targets (set[str]): A set of build_targets that have passed testing.

  Return:
    A list[build_pb2.Build] (that is a subset of `completed_builds`).
  """
  with api.step.nest('get untested builds') as step:
    untested_builds = [
        b for b in completed_builds
        if (api.cros_history.get_build_target(b) not in tested_targets)
    ]
    step.presentation.step_text = '{}/{} builds untested'.format(
        len(untested_builds), len(completed_builds))
    step.presentation.logs['untested_builds'] = [
        api.naming.get_build_title(b) for b in untested_builds
    ]

    return untested_builds


def validate_refs(refs):
  """Assert all given refs start with refs/heads.

  Args:
    refs (list[str]): Refs to validate.

  Raises:
    AssertionError: If any invalid ref is found.
  """
  for ref in refs:
    if not ref.startswith('refs/heads/'):
      raise ValueError('ref %s is missing refs/heads/' % ref)


def maybe_update_manifest_ref(api, update_manifest_refs, ref_key):
  """Update ref in manifest-internal to point to current snapshot.

  Args:
    api (object): See RunSteps documentation.
    update_manifest_refs (dict): Maps ref key (e.g. start) to qualified ref.
    ref_key: Key for ref to access in update_manifest_refs.
  """
  if ref_key in update_manifest_refs:
    with api.step.nest('update manifest %s ref' % ref_key):
      if not api.buildbucket.gitiles_commit.project:
        raise ValueError('orchestrator runs must supply a Gitiles '
                         'commit in their input. Found none. If you\'d like to '
                         'retry a run that did have a Gitiles commit, try doing '
                         'so through RPC explorer, e.g. '
                         'https://screenshot.googleplex.com/FSEm8xB5CS3 '
                         'Got input: %s' % api.buildbucket.gitiles_commit)
      snapshot = api.buildbucket.gitiles_commit
      snapshot_path = api.cros_source.find_project_path(snapshot.project,
                                                        'master')
      with api.context(cwd=api.cros_source.workspace_path.join(snapshot_path)):
        git_repo = 'https://%s/%s' % (snapshot.host, snapshot.project)
        api.git.fetch_ref(git_repo, snapshot.id)
        refspec = '%s:%s' % (snapshot.id, update_manifest_refs[ref_key])
        api.git.push(git_repo, refspec)


def run_tests(api, builds, step_name='run tests'):
  """Shortcut for schedule_tests + collect_tests.

  Args:
    * builds (list or generator of build_pb2.Build]): Builds to test.
    * step_name (str): Optional step name.

  Returns:
    list[swarming.TaskResult]
  """
  with api.step.nest(step_name):
    # TODO(dburger): Hack!!! Remove these isinstance calls when the
    # DeferredResult situation is better understood. Before these were added
    # this passed tests but failed in production. See https://crbug.com/960643.
    tasks = api.test_plan.test_builds('test builds', list(builds))
    if isinstance(tasks, DeferredResult):
      tasks = tasks.get_result()

    results = api.test_plan.collect_tests('collect test results', tasks)
    if isinstance(results, DeferredResult):
      results = results.get_result()

    return results


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
    build = api.buildbucket.ci_build_message(project='chromeos',
                                             bucket='postsubmit',
                                             builder='postsubmit-orchestrator')
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return api.buildbucket.build(build)

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

  yield (api.test('basic') +  #
         postsubmit_orchestrator_build() +
         api.test_plan.simulate_test_builds('run tests.test builds'))

  yield (
      api.test('with_history') +  #
      cq_orchestrator_build_with_gerrit_change() +  #
      api.properties(enable_history=True) +  #
      api.buildbucket.simulated_search_results(
          [], 'Looking for successful builds.buildbucket.search') +  #
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, output=build_pb2.Build.Output(
                  properties=api.cros_history.test_status_property({
                      'amd64-generic': 'success',
                      'arm-generic': 'failure'
                  })))
      ], 'Looking for successful tests.buildbucket.search') +  #
      api.buildbucket.simulated_collect_output(
          [
              build_pb2.Build(
                  id=8922054662172514000,
                  builder={'builder': 'amd64-generic-cq'},
                  status=common_pb2.SUCCESS, input=dict(
                      properties=build_target_property('amd64-generic'))),
              build_pb2.Build(
                  id=8922054662172514001, builder={'builder': 'arm-generic-cq'
                                                  }, status=common_pb2.SUCCESS,
                  input=dict(properties=build_target_property('arm-generic'))),
          ],
          step_name='run child builds.collect',
      ) + api.test_plan.simulate_test_builds('run tests.test builds'))

  yield (api.test('missing_gitiles_commit') +  #
         postsubmit_orchestrator_build_with_no_gitiles() +
         api.properties(update_manifest_refs={
             'start': 'refs/heads/foo',
             'success': 'refs/heads/bar'
         }) +
         api.expect_exception("ValueError"))

  yield (api.test('updates_refs') +  #
         postsubmit_orchestrator_build() +  #
         api.properties(update_manifest_refs={
             'start': 'refs/heads/foo',
             'success': 'refs/heads/bar'
         }) + api.test_plan.simulate_test_builds('run tests.test builds'))

  yield (api.test('bad_update_ref') +  #
         api.properties(update_manifest_refs={'start': 'foo'}) +  #
         api.expect_exception("ValueError"))

  yield (api.test('dry_run') +  #
         postsubmit_orchestrator_build() +  #
         api.cq(dry_run=True))

  yield (
      api.test('critical_child_builder_fails') +  #
      postsubmit_orchestrator_build() +  #
      api.buildbucket.simulated_collect_output(
          [
              build_pb2.Build(id=8922054662172514000, builder={
                  'builder': 'amd64-generic-postsubmit'
              }, status=common_pb2.FAILURE, critical=common_pb2.YES),
              build_pb2.Build(id=8922054662172514001, builder={
                  'builder': 'arm-generic-postsubmit'
              }, status=common_pb2.SUCCESS, critical=common_pb2.NO),
          ],
          step_name='run child builds.collect',
      ) + api.test_plan.simulate_test_builds('run tests.test builds'))

  yield (
      api.test('non-critical_child_builder_fails') +  #
      postsubmit_orchestrator_build() +  #
      api.buildbucket.simulated_collect_output(
          [
              build_pb2.Build(id=8922054662172514000, builder={
                  'builder': 'amd64-generic-postsubmit'
              }, status=common_pb2.SUCCESS, critical=common_pb2.YES),
              build_pb2.Build(id=8922054662172514001, builder={
                  'builder': 'arm-generic-postsubmit'
              }, status=common_pb2.FAILURE, critical=common_pb2.NO),
          ],
          step_name='run child builds.collect',
      ) + api.test_plan.simulate_test_builds('run tests.test builds'))
