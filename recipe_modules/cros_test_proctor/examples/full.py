# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)
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
]

PROPERTIES = {
    'need_tests_builds_serialized':
        Property(kind=list, help='List of serialized Build protos', default=[]),
    'completed_builds_serialized':
        Property(kind=list, help='List of serialized Build protos', default=[]),
    'baseline_validation_count':
        Property(kind=int, help='', default=1),
    'baseline_validation_percent':
        Property(kind=int, help='', default=100),
}


def RunSteps(api, need_tests_builds_serialized, completed_builds_serialized,
             baseline_validation_percent, baseline_validation_count):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  # Deserialized Build protos. The serialization is to get around the recipes
  # requirement that all properties be hashable, and proto messages are not
  # hashable.
  need_tests_builds = []
  for b_str in need_tests_builds_serialized:
    b = Build()
    b.ParseFromString(b_str)
    need_tests_builds.append(b)
  completed_builds = []
  for b_str in completed_builds_serialized:
    b = Build()
    b.ParseFromString(b_str)
    completed_builds.append(b)
  gerrit_changes = []
  if need_tests_builds:
    gerrit_changes = need_tests_builds[0].input.gerrit_changes
  test_plan = api.cros_test_proctor.run_proctor(
      need_tests_builds=need_tests_builds, completed_builds=completed_builds,
      snapshot=snapshot, gerrit_changes=gerrit_changes, enable_history=True,
      baseline_validation_percent=baseline_validation_percent,
      baseline_validation_count=baseline_validation_count)


def GenTests(api):

  def cq_orchestrator_build_with_gerrit_change():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder='cq-orchestrator')
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return build

  def vm_test_build(name):
    output = build_pb2.Build.Output()
    input_proto = build_pb2.Build.Input()
    output.properties.update({'name': name})
    input_proto.properties.update({'name': name})
    return build_pb2.Build(output=output, input=input_proto,
                           status=common_pb2.SUCCESS)

  def input_proto(snapshot, build_target):
    """Generate an instance of Build.Input.

    Args:
      * snapshot(GitilesCommit): The snapshot of the build.
      * build_target (str): The name of the build target.
    """
    return build_pb2.Build.Input(
        properties=api.cros_history.build_target_property(build_target),
        gitiles_commit=snapshot)

  def serialize_builds(builds):
    return [Build.SerializeToString(b) for b in builds]

  vm_tests = [
      vm_test_build('vm-test'),
  ]

  moblab_vm_tests = [
      vm_test_build('moblab-vm-test'),
  ]

  hw_tests = {
      'results': [
          api.skylab.wait_task_result(id='bvt-cq-task-id', name='hw test1',
                                      success=True),
          api.skylab.wait_task_result(id='bvt-inline-task-id', name='hw test2',
                                      success=True),
      ]
  }

  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'arm-generic')),
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      status=common_pb2.STARTED, input=input_proto(
                          None, 'atlas')),
  ]

  yield (
      api.test('tests_with_history') +  #
      api.properties(need_tests_builds_serialized=serialize_builds(builds)) +  #
      # cq_orchestrator_build_with_gerrit_change() +  #
      api.cq(full_run=True) +  #
      api.properties(enable_history=True) +  #
      api.properties(
          completed_builds=serialize_builds(
              [api.cros_history.build_with_passed_tests(['nami/hw/bvt-cq'])]))
      +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))

  builds = [
      build_pb2.Build(
          id=8922054662172514000,
          builder={'builder': 'amd64-generic-postsubmit'},  #
          status=common_pb2.SUCCESS,
          critical=common_pb2.YES,
          input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(
          id=8922054662172514001,
          builder={'builder': 'arm-generic-postsubmit'},  #
          status=common_pb2.FAILURE,
          critical=common_pb2.NO,
          input=input_proto(common_pb2.GitilesCommit(), 'target')),
  ]
  hw_tests = {
      'results': [
          api.skylab.wait_task_result(id='bvt-cq-task-id',
                                      name='bvt-cq-task-id', success=True),
          api.skylab.wait_task_result(id='bvt-inline-task-id',
                                      name='bvt-inline-task-id', success=False),
      ]
  }

  yield (api.test('does_not_run_baseline_validation') +  #
         api.properties(
             need_tests_builds_serialized=serialize_builds(
                 [cq_orchestrator_build_with_gerrit_change()])) +  #
         api.properties(baseline_validation_percent=0) +  #
         api.properties(baseline_validation_count=0) +  #
         api.easy.simulate_json_step(
             'run tests.collect tests.'
             'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
         api.buildbucket.simulated_collect_output(
             vm_tests,
             step_name='run tests.collect tests.collect autotest vm tests') +
         api.buildbucket.simulated_collect_output(
             [], step_name='run tests.collect tests.collect tast vm tests') +
         api.buildbucket.simulated_collect_output(
             moblab_vm_tests,
             step_name='run tests.collect tests.collect moblab vm tests'))

  baseline_results_failure = {
      'results': [
          api.skylab.wait_task_result(id='bvt-inline-task-id',
                                      name='bvt-inline-task-id', success=False),
      ]
  }
  yield (
      api.test('pass_with_baseline_validation') +  #
      api.properties(
          need_tests_builds_serialized=serialize_builds(
              [cq_orchestrator_build_with_gerrit_change()])) +  #
      api.properties(completed_builds_serialized=serialize_builds(builds)) +  #
      api.properties(baseline_validation_percent=100) +  #
      api.properties(baseline_validation_count=1) +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' autotest vm tests') +  #
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' tast vm tests') +  #
      api.easy.simulate_json_step(
          'run baseline tests.collect baseline tests.'
          'collect skylab tasks.skylab wait-tasks', baseline_results_failure))

  baseline_results_success = {
      'results': [
          api.skylab.wait_task_result(id='bvt-inline-task-id', name='hw test2',
                                      success=True),
      ]
  }
  yield (
      api.test('fail_with_baseline_validation') +  #
      api.properties(
          need_tests_builds_serialized=serialize_builds(
              [cq_orchestrator_build_with_gerrit_change()])) +  #
      api.properties(baseline_validation_percent=100) +  #
      api.properties(baseline_validation_count=1) +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +  #
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +  #
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests') +  #
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' autotest vm tests') +  #
      api.buildbucket.simulated_collect_output(
          [], step_name='run baseline tests.collect baseline tests.collect'
          ' tast vm tests') +  #
      api.easy.simulate_json_step(
          'run baseline tests.collect baseline tests.'
          'collect skylab tasks.skylab wait-tasks', baseline_results_success))

  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
  task_id = hw_test_unit.hw_test_cfg.hw_test[0].suite + '-task-id'
  hw_tests = {
      'results': [
          api.skylab.wait_task_result(id=task_id, name='hw test1',
                                      success=True),
      ]
  }

  builds = [api.buildbucket.ci_build_message(builder='amd64-generic-postsubmit',
                                             status='SUCCESS')]
  api.cros_bisect.add_output_props(builds[0], 'amd64-generic')

  yield (
      api.test('with_test_bisection_invocation') +  #
      api.properties(need_tests_builds_serialized=serialize_builds(builds)) +  #
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
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests))

  builds = [
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'staging-arm-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'arm-generic')),
  ]

  yield (
      api.test('staging') +  #
      api.properties(need_tests_builds_serialized=serialize_builds(builds)) +  #
      api.easy.simulate_json_step(
          'run tests.collect tests.'
          'collect skylab tasks.skylab wait-tasks', hw_tests) +  #
      api.buildbucket.simulated_collect_output(
          vm_tests,
          step_name='run tests.collect tests.collect autotest vm tests') +
      api.buildbucket.simulated_collect_output(
          [], step_name='run tests.collect tests.collect tast vm tests') +
      api.buildbucket.simulated_collect_output(
          moblab_vm_tests,
          step_name='run tests.collect tests.collect moblab vm tests'))
