# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties
from PB.recipe_modules.chromeos.cros_test_proctor.examples.full import \
  FullProperties
from PB.recipe_modules.chromeos.cros_test_proctor.proctor import (
    ProctorProperties)
from PB.test_platform.taskstate import TaskState
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_history',
    'cros_relevance',
    'cros_test_proctor',
    'cros_cq_additional_tests',
    'easy',
    'gerrit',
    'skylab_results',
    'src_state',
    'test_util',
    'git_footers',
]


PROPERTIES = FullProperties


def RunSteps(api, properties):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  gerrit_changes = []
  if properties.need_tests_builds:
    gerrit_changes = api.src_state.gerrit_changes

  _ = api.cros_test_proctor.run_proctor(
      need_tests_builds=properties.need_tests_builds,
      snapshot=snapshot,
      gerrit_changes=gerrit_changes,
      enable_history=True,
      run_async=properties.run_async,
      use_test_plan_v2=properties.use_test_plan_v2,
  )

  _ = api.cros_test_proctor.test_summary


def GenTests(api):

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

  cros_test_platforms = [
      build_pb2.Build(id=1234, builder={'builder': 'cros_test_platform'},
                      status=common_pb2.SUCCESS),
      build_pb2.Build(id=4321, builder={'builder': 'cros_test_platform'},
                      status=common_pb2.SUCCESS),
  ]
  ctp_response1 = builds_service_pb2.BatchResponse(responses=[{
      'schedule_build': cros_test_platforms[0]
  }])
  ctp_response2 = builds_service_pb2.BatchResponse(responses=[{
      'schedule_build': cros_test_platforms[1]
  }])

  hw_tests = [
      api.skylab_results.test_with_multi_response(
          bid=4321, names=[
              'htarget.hw.bvt-cq',
              'htarget.hw.bvt-inline',
              'htarget.hw.some-suite',
              'htarget.hw.some-other-suite',
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
      'tests-with-history', cq_orchestrator_build_with_gerrit_change(),
      api.cv(run_mode=api.cv.FULL_RUN), api.cros_history.is_retry(True),
      api.properties(enable_history=True),
      api.properties(
          FullProperties(need_tests_builds=[
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
          'collect skylab tasks v2.buildbucket.collect'))

  yield api.test(
      'with_additional_test_runs', cq_orchestrator_build_with_gerrit_change(),
      api.cv(run_mode=api.cv.FULL_RUN), api.cros_history.is_retry(True),
      api.properties(enable_history=True),
      api.properties(
          FullProperties(need_tests_builds=[
              api.cros_history.build_with_passed_tests(
                  ['arm-generic/hw/bvt-cq'])
          ])),
      api.properties(
          **{
              '$chromeos/cros_cq_additional_tests': {
                  'enable_running_additional_tests': True,
                  'run_additional_tests_as_critical': True,
              }
          }),
      api.git_footers.simulated_get_footers(
          ['AddtnlTestSuite'],
          'run tests.schedule tests.process additional test suites', 1),
      api.git_footers.simulated_get_footers(
          ['missing_build_traget'],
          'run tests.schedule tests.process additional test suites', 2),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_schedule_output(
          ctp_response2, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'))

  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-snapshot'},
                      status=common_pb2.SUCCESS, critical=common_pb2.YES,
                      input=input_proto(
                          None,
                          'amd64-generic',
                      )),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-snapshot'},
                      status=common_pb2.FAILURE, critical=common_pb2.NO,
                      input=input_proto('COMMIT_SHA', 'target')),
  ]

  multi_hw_tests = [
      api.skylab_results.test_with_multi_response(
          bid=1234, names=[
              'htarget.hw.bvt-cq', 'htarget.hw.bvt-inline',
              'htarget.hw.some-suite', 'htarget.hw.some-other-suite'
          ]),
  ]

  yield api.test(
      'multi-req-per-cros-test-platform',
      api.properties(FullProperties(need_tests_builds=builds)),
      api.properties(**{'$chromeos/cros_test_proctor': ProctorProperties()}),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          multi_hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'))

  hw_tests = [
      api.skylab_results.test_with_multi_response(
          bid=4321, names=[
              'htarget.hw.bvt-cq',
              'htarget.hw.bvt-inline',
              'htarget.hw.some-other-suite',
          ], task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
  ]

  hw_tests = [
      api.skylab_results.test_with_multi_response(
          bid=1234, names=[
              'htarget.hw.bvt-cq',
              'htarget.hw.some-other-suite',
          ], task_state=TaskState(verdict=TaskState.VERDICT_FAILED)),
  ]

  builds = [
      api.buildbucket.ci_build_message(builder='amd64-generic-snapshot',
                                       status='SUCCESS')
  ]

  yield api.test(
      'with-async-enabled',
      api.properties(FullProperties(need_tests_builds=builds)),
      api.properties(run_async=True),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.post_check(
          post_process.DoesNotRun, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'))

  yield api.test(
      'with-test-plan-v2', cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          FullProperties(need_tests_builds=builds, use_test_plan_v2=True), **{
              '$chromeos/cros_test_plan_v2': {
                  'migration_configs': [{
                      'host': 'chromium.googlesource.com',
                      'project': 'chromiumos/platform',
                      'file_allowlist_regexps': ['a/b/.*']
                  },],
                  'generate_ctpv1_format': True,
              },
          }),
      api.step_data(
          'run tests.schedule tests.find relevant plans.chromeos.list output files',
          api.file.listdir(['relevant_plan_1.star', 'relevant_plan_2.star']),
      ),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule skylab tests v2.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          hw_tests, 'run tests.collect tests.'
          'collect skylab tasks v2.buildbucket.collect'))

  yield api.test(
      'no-testable-builders',
      api.properties(FullProperties(need_tests_builds=[])),
      api.post_process(post_process.StepTextEquals, 'run tests',
                       'no builds to test'),
      api.post_check(post_process.DoesNotRun, 'run tests.schedule tests'),
      api.post_check(post_process.DoesNotRun, 'run tests.collect tests'),
  )

  builds = [
      api.buildbucket.ci_build_message(builder='test-builder', status='SUCCESS')
  ]

  yield api.test(
      'test-summary-revision',
      api.properties(FullProperties(need_tests_builds=builds)),
  )
