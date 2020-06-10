# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
from PB.recipe_modules.chromeos.cros_test_proctor.proctor import (
    ProctorProperties)
from PB.test_platform.taskstate import TaskState
from recipe_engine.recipe_api import Property

from google.protobuf import json_format
from google.protobuf import struct_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'cros_bisect',
    'cros_history',
    'cros_relevance',
    'cros_test_proctor',
    'easy',
    'gerrit',
    'skylab',
    'test_util',
]

PROPERTIES = {
    'need_tests_builds_serialized':
        Property(kind=list, help='List of serialized Build protos', default=[])
}


def RunSteps(api, need_tests_builds_serialized):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  # Deserialized Build protos. The serialization is to get around the recipes
  # requirement that all properties be hashable, and proto messages are not
  # hashable.
  need_tests_builds = map(Build.FromString, need_tests_builds_serialized)
  gerrit_changes = []
  if need_tests_builds:
    gerrit_changes = need_tests_builds[0].input.gerrit_changes
  test_plan = api.cros_test_proctor.run_proctor(
      need_tests_builds=need_tests_builds, snapshot=snapshot,
      gerrit_changes=gerrit_changes, enable_history=True)


def GenTests(api):

  def vm_test_build(name):
    output = build_pb2.Build.Output()
    input_proto = build_pb2.Build.Input()
    output.properties.update({'name': name})
    input_proto.properties.update({'name': name})
    return build_pb2.Build(output=output, input=input_proto,
                           status=common_pb2.SUCCESS)

  def input_proto(snapshot, build_target, gerrit_changes=None):
    """Generate an instance of Build.Input.

    Args:
      * snapshot(GitilesCommit): The snapshot of the build.
      * build_target (str): The name of the build target.
      * gerrit_changes list(GerritChange): Changes being tested in the build.
    """
    msg = build_pb2.Build.Input(gitiles_commit=snapshot,
                                gerrit_changes=gerrit_changes)
    msg.properties.update(
        api.test_util.build_target_properties(build_target_name=build_target))
    return msg

  def serialize_builds(builds):
    return [Build.SerializeToString(b) for b in builds]

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

  builds = [
      build_pb2.Build(
          id=8922054662172514000, builder={'builder': 'amd64-generic-cq'},
          status=common_pb2.SUCCESS,
          input=input_proto(None, 'amd64-generic',
                            [common_pb2.GerritChange(change=123)])),
      build_pb2.Build(
          id=8922054662172514001, builder={'builder': 'arm-generic-cq'},
          status=common_pb2.STARTED,
          input=input_proto(None, 'arm-generic',
                            [common_pb2.GerritChange(change=123)])),
      build_pb2.Build(
          id=8922054662172514002, builder={'builder': 'atlas-cq'},
          status=common_pb2.STARTED,
          input=input_proto(None, 'atlas',
                            [common_pb2.GerritChange(change=123)])),
  ]

  yield api.test(
      'tests_with_history',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      # cq_orchestrator_build_with_gerrit_change(),
      api.cq(full_run=True),
      api.properties(enable_history=True),
      api.properties(
          need_tests_builds_serialized=serialize_builds([
              api.cros_history.build_with_passed_tests(
                  ['arm-generic/hw/bvt-cq'])
          ])),
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
          step_name='run tests.collect tests.collect moblab vm tests'))

  builds = [
      build_pb2.Build(
          id=8922054662172514000,
          builder={'builder': 'amd64-generic-postsubmit'},
          status=common_pb2.SUCCESS, critical=common_pb2.YES,
          input=input_proto(None, 'amd64-generic',
                            [common_pb2.GerritChange(change=123)])),
      build_pb2.Build(
          id=8922054662172514001, builder={'builder': 'arm-generic-postsubmit'},
          status=common_pb2.FAILURE, critical=common_pb2.NO,
          input=input_proto(common_pb2.GitilesCommit(), 'target',
                            [common_pb2.GerritChange(change=123)])),
  ]

  yield api.test(
      'no_tests_scheduled',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(baseline_validation_percent=0),
      api.properties(baseline_validation_count=0),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-cq.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          [], 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect moblab vm tests'))

  multi_hw_tests = [
      api.skylab.test_with_multi_response(
          id=1234, names=['target.hw.bvt-cq', 'target.hw.bvt-inline']),
  ]

  yield api.test(
      'multi_req_per_cros_test_platform',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(
          **{
              '$chromeos/cros_test_proctor':
                  ProctorProperties(multi_request_ctp_full_enable=True)
          }), api.properties(baseline_validation_percent=0),
      api.properties(baseline_validation_count=0),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          multi_hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))

  hw_tests = [
      api.skylab.test_with_execute_response_json(
          id=1234, task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
      api.skylab.test_with_execute_response_json(
          id=4321, task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
  ]

  yield api.test(
      'does_not_run_baseline_validation',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(baseline_validation_percent=0),
      api.properties(baseline_validation_count=0),
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
          step_name='run tests.collect tests.collect moblab vm tests'))

  baseline_results_failure = [
      api.skylab.test_with_execute_response_json(
          id=4321, task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
  ]
  yield api.test(
      'pass_with_baseline_validation',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(
          **{
              '$chromeos/cros_test_proctor':
                  ProctorProperties(baseline_validation_percent=100)
          }),
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
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' tast vm tests'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2,
          'run baseline tests.schedule baseline tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          baseline_results_failure, 'run baseline tests.collect baseline tests.'
          'collect skylab tasks.buildbucket.collect'))

  baseline_results_success = [
      api.skylab.test_with_execute_response_json(id=4321)
  ]
  yield api.test(
      'fail_with_baseline_validation',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(
          **{
              '$chromeos/cros_test_proctor':
                  ProctorProperties(baseline_validation_percent=100)
          }),
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
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' tast vm tests'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2,
          'run baseline tests.schedule baseline tests.schedule hardware tests.'
          'schedule htarget.hw.bvt-inline.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          baseline_results_success, 'run baseline tests.collect baseline tests.'
          'collect skylab tasks.buildbucket.collect'))

  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
  hw_tests = [
      api.skylab.test_with_execute_response_json(
          id=1234, task_state=TaskState(verdict=TaskState.VERDICT_FAILED))
  ]

  builds = [
      api.buildbucket.ci_build_message(builder='amd64-generic-postsubmit',
                                       status='SUCCESS')
  ]
  api.cros_bisect.add_output_props(builds[0], 'amd64-generic')

  yield api.test(
      'with_test_bisection_invocation',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
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
          'collect skylab tasks.buildbucket.collect'))

  builds = [
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'staging-arm-generic-cq'},
                      status=common_pb2.STARTED,
                      input=input_proto(None, 'arm-generic'))
  ]

  yield api.test(
      'staging',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
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
          step_name='run tests.collect tests.collect moblab vm tests'))
