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
    'recipe_engine/time',
    'build_plan',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'cros_test_proctor',
    'failures',
    'naming',
    'orch_menu',
    'skylab',
    'test_util',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties

from google.protobuf import json_format

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api, properties, config)


def DoRunSteps(api, properties, config):
  snapshot = api.orch_menu.gitiles_commit
  gerrit_changes = api.orch_menu.gerrit_changes
  if (gerrit_changes and properties.enable_history and
      properties.assert_singleton):
    api.orch_menu.wait_for_inflight_orchestrator()

  completed_builds = api.orch_menu.plan_and_run_children(
      enable_history=properties.enable_history)

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
    completed_builds.append(
        api.orch_menu.schedule_wait_build(
            config.orchestrator.follow_on_orchestrator.name,
            config.orchestrator.follow_on_orchestrator.await_completion))

  with api.step.nest('clean up orchestrator') as presentation:
    # Recheck the BuilderConfigs at HEAD, one last time, to see if any failed
    # builders are now noncritical.
    api.cros_infra_config.force_reload()
    child_builder_configs = api.cros_infra_config.safe_get_builder_configs(
        [b.builder.builder for b in completed_builds])
    failures = api.failures.update_non_critical_failures(
        presentation, failures, child_builder_configs)
  return api.failures.aggregate_failures(failures)


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
          input_properties=OrchestratorProperties(
              enable_history=True, update_manifest_refs=dict(
                  build='refs/heads/stable', start='refs/heads/postsubmit'))),
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
