# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_bisect',
    'cros_tags',
    'gerrit',
    'git_footers',
    'orch_menu',
    'skylab',
    'test_util',
]

from google.protobuf import json_format
from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.orch_menu.examples.full import FullProperties
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipe_modules.chromeos.cros_bisect import cros_bisect
from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2
from PB.go.chromium.org.luci.buildbucket.proto.rpc import BatchResponse
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

PROPERTIES = FullProperties


def RunSteps(api, properties):
  build = api.buildbucket.build
  with api.orch_menu.setup_orchestrator(
      missing_ok=properties.missing_ok,
      test_footers=properties.test_footers) as config:
    api.assertions.assertEqual(config, api.orch_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      return
    api.assertions.assertIsNotNone(config)

    expected_changes = build.input.gerrit_changes
    # Add any changes from the config.
    expected_changes.extend([
        json_format.Parse(json_format.MessageToJson(x), GerritChange())
        for x in config.orchestrator.gerrit_changes
    ])
    api.assertions.assertEqual(
        str(expected_changes), str(api.orch_menu.gerrit_changes))

    builds_status = api.orch_menu.plan_and_run_children()

    if not builds_status.fatal_failures:
      builds_status = api.orch_menu.plan_and_run_tests()

    follower = config.orchestrator.follow_on_orchestrator
    if follower.name:
      api.orch_menu.schedule_wait_build(follower.name,
                                        follower.await_completion)

    if properties.expected_completed_builds:
      for actual, expected in zip(api.orch_menu.builds_status.completed_builds,
                                  properties.expected_completed_builds):
        api.assertions.assertEqual(actual, expected)

    expected = properties.expected_recipe_result
    if not expected.status:
      expected = RawResult(status=common_pb2.SUCCESS)
    api.assertions.assertEqual(expected, api.orch_menu.create_recipe_result())


def GenTests(api):
  running_orch = [
      api.test_util.test_orchestrator(cq=True, build_id=8922054662172514000,
                                      status='STARTED').message
  ]
  successful_orch = [
      api.test_util.test_orchestrator(cq=True, build_id=8922054662172514000,
                                      status='SUCCESS').message
  ]
  hw_test_unit = api.cros_bisect.hw_test_unit('amd64-generic')
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

  fail_critical = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514000,
                                     status='FAILURE',
                                     critical=common_pb2.YES).message,
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514001,
                                     status='SUCCESS',
                                     critical=common_pb2.NO).message,
  ]
  fail_non_critical = [
      api.test_util.test_child_build('amd64-generic',
                                     build_id=8922054662172514000,
                                     status='SUCCESS',
                                     critical=common_pb2.YES).message,
      api.test_util.test_child_build('arm-generic',
                                     build_id=8922054662172514001,
                                     status='FAILURE',
                                     critical=common_pb2.NO).message,
  ]

  def vm_test_build(name):
    # The only things we care about are output.properties.name and status.
    return json_format.ParseDict(
        dict(
            output=dict(properties=dict(name=name)), status=common_pb2.SUCCESS),
        Build())

  vm_tests = [vm_test_build('vm-test')]

  moblab_vm_tests = [vm_test_build('moblab-vm-test')]

  cros_test_platforms = [
      Build(id=1234, builder={'builder': 'cros_test_platform'},
            status=common_pb2.SUCCESS),
      Build(id=4321, builder={'builder': 'cros_test_platform'},
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

  def testing_responses(bvt_cq=None, bvt_inline=None, skylab=None,
                        autotest=None, tast=None, moblab=None):
    ret = recipe_test_api.TestData(None)
    sched_tmpl = ('run tests.schedule tests.schedule hardware tests.'
                  'schedule htarget.hw.%s.buildbucket.schedule')
    vm_tmpl = 'run tests.collect tests.collect %s vm tests'
    if bvt_cq is not None:
      ret += api.buildbucket.simulated_schedule_output(bvt_cq,
                                                       sched_tmpl % 'bvt-cq')
    if bvt_inline is not None:
      ret += api.buildbucket.simulated_schedule_output(
          bvt_inline, sched_tmpl % 'bvt-inline')
    if skylab is not None:
      ret += api.buildbucket.simulated_collect_output(
          skylab, 'run tests.collect tests.'
          'collect skylab tasks.buildbucket.collect')
    if autotest is not None:
      ret += api.buildbucket.simulated_collect_output(
          autotest, step_name=vm_tmpl % 'autotest')
    if tast is not None:
      ret += api.buildbucket.simulated_collect_output(
          tast, step_name=vm_tmpl % 'tast')
    if moblab is not None:
      ret += api.buildbucket.simulated_collect_output(
          moblab, step_name=vm_tmpl % 'moblab')
    return ret

  yield api.orch_menu.test(
      'basic',
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
  )

  yield api.orch_menu.test(
      'two-footers',
      api.properties(
          FullProperties(expect_missing_config=True,
                         test_footers='foot1\nfoot2')))

  yield api.orch_menu.test(
      'bad-ref',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      input_properties=OrchestratorProperties(
          update_manifest_refs=OrchestratorProperties.UpdateManifestRefs(
              start='missing-ref-heads')))

  yield api.orch_menu.test(
      'required-missing-config',
      api.properties(FullProperties(expect_missing_config=True)),
      builder='no-config')

  yield api.orch_menu.test(
      'forgiven-missing-config',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      builder='no-config')

  yield api.orch_menu.test(
      'fails-if-changes-not-submittable',
      api.gerrit.simulated_changes_are_submittable(submittable=False), cq=True)

  # Joins an inflight orchestrator run.
  yield api.orch_menu.test(
      'inflight-orchestrator',
      api.buildbucket.simulated_search_results(
          running_orch, step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_collect_output(
          successful_orch,
          'find inflight orchestrator.waiting for existing runs'),
      api.properties(
          FullProperties(expected_completed_builds=builds,
                         expected_enable_history=True)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
      input_properties={
          '$chromeos/orch_menu':
              dict(enable_history=True, assert_singleton=True)
      },
      cq=True,
  )

  # Runs when there is no inflight orchestrator.
  yield api.orch_menu.test(
      'no-inflight-orchestrator',
      api.buildbucket.simulated_search_results(
          [], step_name='find inflight orchestrator.'
          'find matching builds.buildbucket.search'),
      api.properties(
          FullProperties(expected_completed_builds=builds,
                         expected_enable_history=True)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      api.git_footers.simulated_get_footers([], 'run builds.get build history'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
      input_properties={
          '$chromeos/orch_menu':
              dict(enable_history=True, assert_singleton=True)
      },
      cq=True,
  )

  # Collect times out
  yield api.orch_menu.test(
      'collect-children-timeout',
      api.step_data('run builds.collect.wait', retcode=1),
      api.buildbucket.simulated_get_multi(builds, 'run builds.get'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
  )

  yield api.orch_menu.test(
      'quota-scheduler-override',
      api.buildbucket.simulated_collect_output(builds,
                                               step_name='run builds.collect'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
      cq=True,
      tags=api.cros_tags.tags(cq_cl_tag='pupr:chromeos-base/chromeos-chrome'),
  )

  bisect_builds = [
      api.test_util.test_child_build('amd64-generic', status='SUCCESS').message
  ]
  api.cros_bisect.add_output_props(bisect_builds[0], 'amd64-generic')
  # Bisection
  yield api.orch_menu.test(
      'with-test-bisection',
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  cros_bisect.CrosBisectProperties(
                      test=dict(hw_test_failures=[
                          dict(
                              test_spec=json_format.MessageToJson(hw_test_unit))
                      ]))
          }),
      api.buildbucket.simulated_collect_output(bisect_builds,
                                               'run builds.collect'),
      api.buildbucket.simulated_schedule_output(
          ctp_response1, 'run tests.schedule tests.schedule hardware tests.'
          'schedule kip.hw.bvt-cq.buildbucket.schedule'),
      testing_responses(
          skylab=[api.skylab.test_with_execute_response_json(id=1234)]),
      api.properties(FullProperties(expected_completed_builds=bisect_builds)),
      bucket='bisect', builder='bisecting-orchestrator')

  # Follow-on orchestrator.
  yield api.orch_menu.test(
      'with-follow-on',
      api.properties(
          FullProperties(expected_completed_builds=builds + successful_orch)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
      api.buildbucket.simulated_schedule_output(
          BatchResponse(responses=[dict(schedule_build=running_orch[0])]),
          'run follow on orchestrator.buildbucket.schedule'),
      api.buildbucket.simulated_collect_output(
          successful_orch, 'run follow on orchestrator.collect'),
      bucket='toolchain', builder='orderfile-generate-orchestrator')

  # Follow-on orchestrator times out.
  yield api.orch_menu.test(
      'with-follow-on-timeout',
      api.properties(
          FullProperties(expected_completed_builds=builds + successful_orch)),
      api.buildbucket.simulated_collect_output(builds, 'run builds.collect'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
      api.buildbucket.simulated_schedule_output(
          BatchResponse(responses=[dict(schedule_build=running_orch[0])]),
          'run follow on orchestrator.buildbucket.schedule'),
      api.step_data('run follow on orchestrator.collect.wait', retcode=1),
      api.buildbucket.simulated_get_multi(successful_orch,
                                          'run follow on orchestrator.get'),
      bucket='toolchain', builder='orderfile-generate-orchestrator')

  summary = (
      '1 build failed\n\n- amd64-generic-postsubmit: [build page](https://'
      'beefy-dot-cr-buildbucket.appspot.com/build/8922054662172514000)')
  yield api.orch_menu.test(
      'critical_child_builder_fails',
      api.properties(
          FullProperties(
              expected_completed_builds=fail_critical,
              expected_recipe_result=RawResult(status=common_pb2.FAILURE,
                                               summary_markdown=summary))),
      api.buildbucket.simulated_collect_output(fail_critical,
                                               step_name='run builds.collect'),
  )

  yield api.orch_menu.test(
      'non-critical_child_builder_fails',
      api.properties(
          FullProperties(expected_completed_builds=fail_non_critical)),
      api.buildbucket.simulated_collect_output(fail_non_critical,
                                               step_name='run builds.collect'),
      testing_responses(ctp_response1, ctp_response2, hw_tests, vm_tests, [],
                        moblab_vm_tests),
  )
