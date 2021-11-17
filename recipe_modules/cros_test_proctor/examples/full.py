# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
from PB.recipe_modules.chromeos.cros_test_proctor.proctor import (
    ProctorProperties)
from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from google.protobuf import json_format

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
    'src_state',
    'test_util',
]

PROPERTIES = {
    'need_tests_builds_serialized':
        Property(kind=list, help='List of serialized Build protos', default=[]),
    'run_async':
        Property(kind=bool, help='Should we run the proctor in async mode',
                 default=False),
}


def RunSteps(api, need_tests_builds_serialized, run_async):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  # Deserialized Build protos. The serialization is to get around the recipes
  # requirement that all properties be hashable, and proto messages are not
  # hashable.
  need_tests_builds = map(build_pb2.Build.FromString,
                          need_tests_builds_serialized)
  gerrit_changes = []
  if need_tests_builds:
    gerrit_changes = api.src_state.gerrit_changes

  _ = api.cros_test_proctor.run_proctor(need_tests_builds=need_tests_builds,
                                        snapshot=snapshot,
                                        gerrit_changes=gerrit_changes,
                                        enable_history=True,
                                        run_async=run_async)

  _ = api.cros_test_proctor.test_summary


def GenTests(api):

  def vm_test_build(name, status=common_pb2.SUCCESS, critical=True):
    output = build_pb2.Build.Output()
    input_proto = build_pb2.Build.Input()
    output.properties.update({'name': name})
    input_proto.properties.update({'name': name})
    return build_pb2.Build(
        output=output, input=input_proto, status=status,
        critical=common_pb2.YES if critical else common_pb2.NO)

  def input_proto(snapshot, build_target):
    """Generate an instance of Build.Input.

    Args:
      * snapshot(GitilesCommit): The snapshot of the build.
      * build_target (str): The name of the build target.
      * gerrit_changes list(GerritChange): Changes being tested in the build.
    """
    return api.test_util.test_build(
        cq=True, revision=snapshot, input_properties=BuildMenuProperties(
            build_target=BuildTarget(name=build_target))).message.input

  def serialize_builds(builds):
    return [build_pb2.Build.SerializeToString(b) for b in builds]

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
      api.skylab.test_with_multi_response(
          bid=4321, names=[
              'htarget.hw.bvt-cq',
              'htarget.hw.bvt-inline',
              'htarget.hw.some-suite',
              'ttarget.hw.some-other-suite',
          ]),
  ]

  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SUCCESS, input=input_proto(
                          None,
                          'amd64-generic',
                      )),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-cq'},
                      status=common_pb2.STARTED, input=input_proto(
                          None,
                          'arm-generic',
                      )),
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      status=common_pb2.STARTED, input=input_proto(
                          None,
                          'atlas',
                      )),
  ]

  def cq_orchestrator_build_with_gerrit_change(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    build = api.buildbucket.try_build_message(project='chromeos', **kwargs)
    return api.buildbucket.build(build)

  yield api.test(
      'tests_with_history',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      cq_orchestrator_build_with_gerrit_change(),
      api.cq(run_mode=api.cq.FULL_RUN), api.cros_history.is_retry(True),
      api.properties(enable_history=True),
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(resultdb_elegible_projects=['chromeos'])
          }),
      api.properties(
          need_tests_builds_serialized=serialize_builds([
              api.cros_history.build_with_passed_tests(
                  ['arm-generic/hw/bvt-cq'])
          ])),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'),
      api.buildbucket.simulated_collect_output([
          vm_test_build('vm-test'),
          vm_test_build('vm-test-2', status=common_pb2.FAILURE, critical=False)
      ], step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast GCE tests'))

  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.SUCCESS, critical=common_pb2.YES,
                      input=input_proto(
                          None,
                          'amd64-generic',
                      )),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-postsubmit'},
                      status=common_pb2.FAILURE, critical=common_pb2.NO,
                      input=input_proto('COMMIT_SHA', 'target')),
  ]

  multi_hw_tests = [
      api.skylab.test_with_multi_response(
          bid=1234, names=[
              'htarget.hw.bvt-cq', 'htarget.hw.bvt-inline',
              'htarget.hw.some-suite', 'ttarget.hw.some-other-suite'
          ]),
  ]

  yield api.test(
      'multi_req_per_cros_test_platform',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(**{'$chromeos/cros_test_proctor': ProctorProperties()}),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          multi_hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'),
      api.buildbucket.simulated_collect_output(
          [vm_test_build('vm-test')],
          step_name='run tests.collect tests.collect autotest vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests'),
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast GCE tests'))

  hw_tests = [
      api.skylab.test_with_multi_response(
          bid=4321, names=[
              'htarget.hw.bvt-cq',
              'htarget.hw.bvt-inline',
              'ttarget.hw.some-other-suite',
          ], task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
  ]

  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
  hw_tests = [
      api.skylab.test_with_multi_response(
          bid=1234, names=[
              'htarget.hw.bvt-cq',
              'ttarget.hw.some-other-suite',
          ], task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
  ]

  builds = [
      api.buildbucket.ci_build_message(builder='amd64-generic-postsubmit',
                                       status='SUCCESS')
  ]
  api.cros_bisect.add_properties(builds[0], 'amd64-generic')

  yield api.test(
      'with_test_bisection_invocation',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  CrosBisectProperties(
                      test_bisection_percent=20, test_bisection_count=10, test={
                          'hw_test_failures': [{
                              'test_spec':
                                  json_format.MessageToJson(hw_test_unit)
                          },],
                      })
          }),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'))

  yield api.test(
      'with_async_enabled',
      api.properties(need_tests_builds_serialized=serialize_builds(builds)),
      api.properties(run_async=True),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.post_check(
          post_process.DoesNotRun, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'))
