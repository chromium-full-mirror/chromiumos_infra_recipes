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

import json

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.builds_service import (
    BatchResponse)
from PB.recipes.chromeos.orchestrator import OrchestratorProperties

from recipe_engine import post_process

PROPERTIES = OrchestratorProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(missing_ok=True) as config:
    if config:
      DoRunSteps(api, properties, config)
    return api.orch_menu.create_recipe_result()


def DoRunSteps(api, properties, config):

  # Run the child builders.
  api.orch_menu.plan_and_run_children()

  # Run any HW tests.
  api.orch_menu.plan_and_run_tests()

  # Launch any specified follow on orchestrator.
  follower = config.orchestrator.follow_on_orchestrator
  if not api.orch_menu.builds_status.fatal_failures and follower.name:
    api.orch_menu.schedule_wait_build(follower.name, follower.await_completion)


def GenTests(api):

  def test_orchestrator(with_manifest_refs=False, with_history=False, **kwargs):
    """Generate a test build proto for the postsubmit orchestrator."""
    props = api.orch_menu.get_default_module_properties(
        with_manifest_refs=with_manifest_refs, with_history=with_history)
    kwargs.setdefault('input_properties', props)
    return api.test_util.test_orchestrator(**kwargs).build

  def vm_test_build(name):
    # The only things we care about are output.properties.name and status.
    return api.test_util.test_build(builder='vmtest', revision=None,
                                    output_properties=dict(name=name),
                                    status='SUCCESS').message

  vm_tests = [vm_test_build('vm-test')]

  moblab_vm_tests = [vm_test_build('moblab-vm-test')]

  ctp_response1 = BatchResponse(responses=[
      dict(
          schedule_build=api.test_util.test_build(
              build_id=1234, bucket='testplatform',
              builder='cros_test_platform', status='SUCCESS',
              bot_size=None).message)
  ])
  ctp_response2 = BatchResponse(responses=[
      dict(
          schedule_build=api.test_util.test_build(
              build_id=4321, bucket='testplatform',
              builder='cros_test_platform', status='SUCCESS',
              bot_size=None).message)
  ])

  hw_tests = [
      api.skylab.test_with_execute_response_json(id=1234),
      api.skylab.test_with_execute_response_json(id=4321),
  ]

  inflight_orch = api.test_util.test_orchestrator(cq=True,
                                                  build_id=8922054662172513001,
                                                  status='STARTED').message

  follow_on_orch = api.test_util.test_orchestrator(
      build_id=8922054662172515000, bucket='toolchain',
      builder='orderfile-verify-orchestrator', status='SUCCESS').message

  builds = [
      api.test_util.test_child_build('amd64-generic', cq=True,
                                     build_id=8922054662172514000,
                                     status='SUCCESS',
                                     output_properties=dict(build_cost=10.0),
                                     critical='YES').message,
      api.test_util.test_child_build('arm-generic', cq=True,
                                     build_id=8922054662172514001,
                                     status='STARTED', critical='YES').message,
      api.test_util.test_child_build('atlas', cq=True,
                                     build_id=8922054662172514002,
                                     start_time=1562475245, status='SUCCESS',
                                     revision=None, critical='YES').message,
  ]

  # we have three here to properly exercise "prioritize_builds"
  existing_annealing_builds = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514102,
                                     bucket='snapshot',
                                     status='STARTED').message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514103,
                                     bucket='snapshot',
                                     status='SUCCESS').message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514105,
                                     bucket='snapshot',
                                     status='SUCCESS').message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514104,
                                     bucket='snapshot',
                                     status='SCHEDULED').message,
  ]

  followon_resp1 = BatchResponse(
      responses=[dict(schedule_build=follow_on_orch)])

  yield api.test(
      'basic',
      test_orchestrator(with_history=True, with_manifest_refs=True),
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
      test_orchestrator(cq=True, with_history=True),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      api.buildbucket.simulated_search_results(
          [x for x in builds if x.status == common_pb2.SUCCESS],
          'run builds.get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [x for x in builds if x.status != common_pb2.SUCCESS],
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
      test_orchestrator(with_history=True, with_manifest_refs=True),
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
      test_orchestrator(cq=True, with_history=True),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      api.buildbucket.simulated_search_results(
          [inflight_orch], step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [inflight_orch],
          'find inflight orchestrator.waiting for existing runs'),
      api.buildbucket.simulated_search_results(
          [x for x in builds if x.status == common_pb2.SUCCESS],
          'run builds.get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [x for x in builds if x.status != common_pb2.SUCCESS],
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
      test_orchestrator(cq=True, with_history=True),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      api.buildbucket.simulated_search_results(
          [], step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          [x for x in builds if x.status == common_pb2.SUCCESS],
          'run builds.get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [x for x in builds if x.status != common_pb2.SUCCESS],
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
      test_orchestrator(with_manifest_refs=True),
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
      test_orchestrator(revision=None, with_manifest_refs=True),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'update manifest-internal ref refs/heads/postsubmit'),
      api.post_check(post_process.MustRun,
                     'update manifest ref refs/heads/stable'),
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
      api.buildbucket.simulated_collect_output(
          [follow_on_orch], 'run follow on orchestrator.collect'),
  )

  yield api.test(
      'missing_gitiles_commit_with_defaults',
      test_orchestrator(revision=None, with_manifest_refs=True),
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
      'missing_gitiles_commit_with_changes',
      test_orchestrator(revision=None, cq=True, with_history=True),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      api.buildbucket.simulated_search_results(
          [x for x in builds if x.status == common_pb2.SUCCESS],
          'run builds.get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [x for x in builds if x.status != common_pb2.SUCCESS],
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

  def verify_qs_account_pupr(check, steps):
    data = json.loads(
        steps['run tests.schedule tests.schedule hardware tests.'
              'schedule htarget.hw.bvt-cq.buildbucket.schedule'].stdin)
    return check(data['requests'][0]['scheduleBuild']['properties']['request']
                 ['params']['scheduling']['qsAccount'] == u'pupr')

  yield api.test(
      'quota_scheduler_override',
      test_orchestrator(
          cq=True, with_history=True, tags=api.cros_tags.tags(
              cq_cl_tag='pupr:chromeos-base/chromeos-chrome')),
      api.post_check(post_process.StatusSuccess),
      api.post_check(verify_qs_account_pupr),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      api.buildbucket.simulated_search_results(
          [x for x in builds if x.status == common_pb2.SUCCESS],
          'run builds.get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [x for x in builds if x.status != common_pb2.SUCCESS],
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
      'retry_only_critical_builds',
      test_orchestrator(cq=True, with_history=True),
      api.post_check(post_process.StatusSuccess),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      api.buildbucket.simulated_search_results(
          [x for x in builds if x.status == common_pb2.SUCCESS],
          'run builds.get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          [x for x in builds if x.status != common_pb2.SUCCESS],
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
      test_orchestrator(with_manifest_refs=True),
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
      test_orchestrator(with_manifest_refs=True),
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
