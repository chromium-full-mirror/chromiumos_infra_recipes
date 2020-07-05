# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'cros_tags',
    'git_footers',
    'orch_menu',
    'skylab',
    'test_util',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties

from recipe_engine import post_process
from google.protobuf import json_format

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api, properties, config)
    return api.orch_menu.create_recipe_result()


def DoRunSteps(api, properties, config):
  snapshot = api.orch_menu.gitiles_commit
  gerrit_changes = api.orch_menu.gerrit_changes

  api.orch_menu.plan_and_run_children()

  # Run any HW tests.
  api.orch_menu.plan_and_run_tests()

  # Launch any specified follow on orchestrator.
  follower = config.orchestrator.follow_on_orchestrator
  if not api.orch_menu.builds_status.fatal_failures and follower.name:
    api.orch_menu.schedule_wait_build(follower.name, follower.await_completion)


def GenTests(api):

  def orch_menu_properties(**kwargs):
    return {'$chromeos/orch_menu': kwargs}

  def test_orchestrator(cq=False, **kwargs):
    """Generate a test build proto for the postsubmit orchestrator."""
    if not cq:
      kwargs.setdefault(
          'input_properties',
          orch_menu_properties(
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
  ctp_response1 = builds_service_pb2.BatchResponse(
      responses=[dict(schedule_build=cros_test_platforms[0])])
  ctp_response2 = builds_service_pb2.BatchResponse(
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

  followon_resp1 = builds_service_pb2.BatchResponse(responses=[
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
      api.post_check(post_process.StatusSuccess),
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
          input_properties=orch_menu_properties(assert_singleton=True,
                                                enable_history=True)),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
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
          input_properties=orch_menu_properties(assert_singleton=True,
                                                enable_history=True)),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
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
          input_properties=orch_menu_properties(
              assert_singleton=True,
              enable_history=True, update_manifest_refs=dict(
                  build='refs/heads/stable', start='refs/heads/postsubmit'))),
      api.post_check(post_process.StatusSuccess),
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
          input_properties=orch_menu_properties(enable_history=True,
                                                assert_singleton=True)),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
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
          input_properties=orch_menu_properties(enable_history=True,
                                                assert_singleton=True)),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
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
          input_properties=orch_menu_properties(update_manifest_refs={
              'start': 'refs/heads/foo',
              'build': 'refs/heads/bar'
          })),
      api.post_check(post_process.StatusSuccess),
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
          input_properties=orch_menu_properties(update_manifest_refs={
              'start': 'refs/heads/foo',
              'build': 'refs/heads/bar'
          })),
      api.post_check(post_process.StatusSuccess),
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
      api.post_check(post_process.StatusSuccess),
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
      api.post_check(post_process.StatusSuccess),
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
      api.post_check(post_process.StatusSuccess),
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
      'quota_scheduler_override',
      test_orchestrator(
          cq=True,
          input_properties=orch_menu_properties(assert_singleton=True,
                                                enable_history=True),
          tags=api.cros_tags.tags(
              cq_cl_tag='pupr:chromeos-base/chromeos-chrome')),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
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
          input_properties=orch_menu_properties(assert_singleton=True,
                                                enable_history=True)),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
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
      api.post_check(post_process.StatusAnyFailure),
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
      api.post_check(post_process.StatusSuccess),
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
