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
    'cros_test_plan',
    'cros_version',
    'failures',
    'git',
    'gitiles',
    'naming',
    'skylab',
]

from PB.chromite.api.test import VmTestRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipes.chromeos.test_vm import TestVmProperties

from google.protobuf import json_format
from google.protobuf import struct_pb2

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  validate_refs(properties.update_manifest_refs)

  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  manifest_commit = api.buildbucket.gitiles_commit
  if not manifest_commit.project:
    manifest_commit = load_manifest_commit_from_snapshot(api)

  # Point start ref to the input snapshot if specified.
  maybe_update_manifest_ref(api, properties.update_manifest_refs, 'start')

  requests = []
  completed_builds = []
  passed_builders = set()

  if properties.enable_history and gerrit_changes:
    completed_builds = api.cros_history.get_passed_builds(
        api.buildbucket.build.input.gerrit_changes)
    passed_builders = set(build.builder.builder for build in completed_builds)

  orchestrator_builder_config = api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)
  for child in orchestrator_builder_config.orchestrator.children:
    if child not in passed_builders:
      child_builder_config = api.cros_infra_config.get_builder_config(child)
      requests.append(
          api.buildbucket.schedule_request(
              gitiles_commit=manifest_commit,
              builder=child,
              critical=child_builder_config.general.critical.value))

  if requests:
    # As of 2019-05-16, buildbucket.run uses an old-style collect command
    # that doesn't return all of the fields we need on the Build proto.
    # We thus need to do a get_multi call to get the fully populated Builds.
    # TODO: revert https://crrev.com/c/1615374 once buildbucket.run's call
    # to collect is improved to return the full proto.
    new_builds = api.buildbucket.run(
        requests, timeout=60 * 60 * 4, step_name='run builds',
        url_title_fn=api.naming.get_build_title)
    populated_builds = api.buildbucket.get_multi(
        [b.id for b in new_builds], step_name='get full build protos')
    completed_builds += populated_builds.values()

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
      test_plan = api.cros_test_plan.generate(
          need_tests_builds, manifest_commit.id)

      # We will not run tests that have already passed for this patch set.
      passed_tests = []
      if properties.enable_history and gerrit_changes:
        passed_tests = api.cros_history.get_passed_tests(gerrit_changes)

      with api.step.nest('schedule hardware tests'):
        skylab_tasks = [
            api.skylab.create_suite(test, unit.common.build_payload)
            for unit in test_plan.hw_test_units
            for test in unit.hw_test_cfg.hw_test
            if test.common.display_name not in passed_tests
        ]

      vm_tests = api.buildbucket.schedule([
          api.buildbucket.schedule_request(
              gitiles_commit=manifest_commit,
              builder='test_vm',
              critical=test.common.critical.value,
              properties=json_format.MessageToDict(
                  TestVmProperties(
                      name=test.common.display_name,
                      build_target=unit.common.build_target,
                      test_harness=VmTestRequest.AUTOTEST,
                      build_payload=unit.common.build_payload,
                      expressions=[test.test_suite])))
          for unit in test_plan.vm_test_units
          for test in unit.vm_test_cfg.vm_test
          if test.common.display_name not in passed_tests
      ], step_name='schedule autotest vm tests')

      vm_tests += api.buildbucket.schedule([
          api.buildbucket.schedule_request(
              gitiles_commit=manifest_commit,
              builder='test_vm',
              critical=test.common.critical.value,
              properties=json_format.MessageToDict(
                  TestVmProperties(
                      name=test.common.display_name,
                      build_target=unit.common.build_target,
                      test_harness=VmTestRequest.TAST,
                      build_payload=unit.common.build_payload,
                      expressions=[t.test_expr for t in test.tast_test_expr])))
          for unit in test_plan.tast_vm_test_units
          for test in unit.tast_vm_test_cfg.tast_vm_test
          if test.common.display_name not in passed_tests
       ], step_name='schedule tast vm tests')

    with api.step.nest('collect tests'):
      hw_results = []
      if skylab_tasks:
        hw_results = api.skylab.wait_suites(skylab_tasks)

      vm_results = []
      if vm_tests:
        vm_results = api.buildbucket.collect_builds(
            [vt.id for vt in vm_tests]).values()

      # Record test results.
      # TODO(evanhernandez): Record VM test history.
      passed_tests = [
          hw_result.task.test.common.display_name for hw_result in hw_results
          if not api.failures.is_hw_test_failure(hw_result)
       ]
      api.cros_history.set_passed_tests(passed_tests)

  # Verify builds/tests in a deferred context so that all failures appear.
  with api.step.nest('results'):
    with api.step.defer_results():
      api.failures.raise_failed_builds(completed_builds)
      api.failures.raise_failed_hw_tests(hw_results)
      api.failures.raise_failed_vm_tests(vm_results)

  # Victory! If we've made it this far, the child builders were successful
  # and we can update the success manifest ref if it is specified.
  maybe_update_manifest_ref(api, properties.update_manifest_refs, 'success')


def load_manifest_commit_from_snapshot(api):
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


def validate_refs(refs):
  """Assert the given refs start with refs/heads.

  Args:
    refs (UpdateManifestRefs): Refs to validate.

  Raises:
    AssertionError: If any invalid ref is found.
  """
  validate_ref(refs.start, 'start')
  validate_ref(refs.success, 'success')


def validate_ref(ref, name):
  """Assert the given ref starts with refs/heads.

  Args:
    ref (string): the ref to validate, if any.
    name (string): name of ref to validate.
  """
  if ref and not ref.startswith('refs/heads/'):
    raise ValueError('%s ref %s is missing refs/heads/' % (name, ref))


def maybe_update_manifest_ref(api, update_manifest_refs, name):
  """Update ref in manifest-internal to point to current snapshot.

  Args:
    api (object): See RunSteps documentation.
    update_manifest_refs (UpdateManifestRefs): refs to maybe update.
    name (string): name of ref to maybe update. Must correspond to
        a property name on update_manifest_refs.
  """
  ref = getattr(update_manifest_refs, name)
  if ref:
    with api.step.nest('update manifest %s ref' % name):
      if not api.buildbucket.gitiles_commit.project:
        raise ValueError('orchestrator runs must supply a Gitiles '
                         'commit in their input. Found none. If you\'d like to '
                         'retry a run that did have a Gitiles commit, try doing '
                         'so through RPC explorer, e.g. '
                         'https://screenshot.googleplex.com/FSEm8xB5CS3 '
                         'Got input: %s' % api.buildbucket.gitiles_commit)
      snapshot = api.buildbucket.gitiles_commit
      checkout_path = api.path.mkdtemp()
      with api.context(cwd=checkout_path):
        git_repo = 'https://%s/%s' % (snapshot.host, snapshot.project)
        api.git.clone(git_repo)
        api.git.fetch_ref(git_repo, snapshot.id)
        refspec = '%s:%s' % (snapshot.id, ref)
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

  yield (api.test('basic') + postsubmit_orchestrator_build())

  builds = [
      build_pb2.Build(
          id=8922054662172514000,
          builder={'builder': 'amd64-generic-cq'},
          status=common_pb2.SUCCESS, input=dict(
              properties=build_target_property('amd64-generic'))),
      build_pb2.Build(
          id=8922054662172514001, builder={'builder': 'arm-generic-cq'
                                          }, status=common_pb2.SUCCESS,
          input=dict(properties=build_target_property('arm-generic'))),
  ]
  yield (
      api.test('with_history') +  #
      cq_orchestrator_build_with_gerrit_change() +  #
      api.properties(enable_history=True) +  #
      api.buildbucket.simulated_search_results(
          [], 'get change build history.buildbucket.search') +  #
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_passed_tests(['nami/hw/bvt-cq'])],
          'run tests.schedule tests.get change test history.buildbucket.search') + #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +
      api.buildbucket.simulated_get_multi(
          builds, step_name='get full build protos'))

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
         }))

  yield (api.test('bad_update_ref') +  #
         api.properties(update_manifest_refs={'start': 'foo'}) +  #
         api.expect_exception("ValueError"))

  yield (api.test('dry_run') +  #
         postsubmit_orchestrator_build() +  #
         api.cq(dry_run=True))

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-postsubmit'
      }, status=common_pb2.FAILURE, critical=common_pb2.YES),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-postsubmit'
      }, status=common_pb2.SUCCESS, critical=common_pb2.NO),
  ]
  yield (
      api.test('critical_child_builder_fails') +  #
      postsubmit_orchestrator_build() +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +
      api.buildbucket.simulated_get_multi(
          builds, step_name='get full build protos'))

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-postsubmit'
      }, status=common_pb2.SUCCESS, critical=common_pb2.YES),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-postsubmit'
      }, status=common_pb2.FAILURE, critical=common_pb2.NO),
  ]
  yield (
      api.test('non-critical_child_builder_fails') +  #
      postsubmit_orchestrator_build() +  #
      api.buildbucket.simulated_collect_output(
          builds, step_name='run builds.collect') +
      api.buildbucket.simulated_get_multi(
          builds, step_name='get full build protos'))
