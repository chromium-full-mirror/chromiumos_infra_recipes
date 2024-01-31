# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_test_proctor.proctor import \
  ProctorProperties
from PB.recipe_modules.chromeos.cros_test_proctor.tests.schedule_tests import \
  ScheduleTestsProperties
from recipe_engine.post_process import DropExpectation
from recipe_engine.post_process import LogContains
from recipe_engine.post_process import MustRun
from recipe_engine.post_process import PropertyEquals

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_proctor',
    'cros_test_plan',
]


PROPERTIES = ScheduleTestsProperties


def RunSteps(api, properties):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  _ = api.cros_test_proctor.schedule_tests(
      test_plan, list(set(properties.passed_tests)),
      properties.previously_failed_now_exonerable_hw_suites,
      properties.previously_failed_now_exonerable_vm_suites,
      api.cros_test_proctor.timeout, snapshot, is_retry=properties.is_retry)


def GenTests(api):

  all_hw_test_names = [
      'htarget.hw.bvt-cq',
      'htarget.hw.bvt-inline',
      'htarget.hw.some-other-suite',
      'htarget.hw.some-suite',
  ]
  all_tast_vm_test_names = [
      'ttarget.tast.sweet-informational',
      'ttarget.tast.sweet_shard_1_of_2',
      'ttarget.tast.sweet_shard_2_of_2',
  ]
  all_tast_gce_test_names = [
      'ttarget.tast_gce.sweet',
      'ttarget.tast_gce.sweet-informational',
  ]

  tast_vm_test_build_responses = []
  for name in all_tast_vm_test_names:
    build = api.buildbucket.ci_build_message()
    build.input.properties['name'] = name
    api.buildbucket.build(build)
    tast_vm_test_build_responses.append({'schedule_build': build})
  tast_vm_test_response = builds_service_pb2.BatchResponse(
      responses=tast_vm_test_build_responses)

  tast_gce_test_build_responses = []
  for name in all_tast_gce_test_names:
    build = api.buildbucket.ci_build_message()
    build.input.properties['name'] = name
    api.buildbucket.build(build)
    tast_gce_test_build_responses.append({'schedule_build': build})
  tast_gce_test_response = builds_service_pb2.BatchResponse(
      responses=tast_gce_test_build_responses)

  yield api.test(
      'basic',
      api.post_check(PropertyEquals, 'scheduled_hw_tests', all_hw_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_vm_tests',
                     all_tast_vm_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_gce_tests',
                     all_tast_gce_test_names),
      api.buildbucket.simulated_schedule_output(tast_vm_test_response,
                                                'schedule tast vm tests'),
      api.buildbucket.simulated_schedule_output(tast_gce_test_response,
                                                'schedule tast GCE tests'),
  )

  # Non-critical tests are not run on retries.
  passed_tests = [
      'htarget.hw.bvt-cq',
      'htarget.hw.some-suite',
      'ttarget.tast_gce.sweet',
      'ttarget.tast.sweet_shard_1_of_2',
      'ttarget.tast.sweet-informational',
  ]
  expected_hw_test_names = [
      'htarget.hw.bvt-inline',
      'htarget.hw.some-other-suite',
  ]
  expected_tast_vm_test_names = ['ttarget.tast.sweet_shard_2_of_2']
  expected_tast_gce_test_names = []
  yield api.test(
      'retry',
      api.properties(
          ScheduleTestsProperties(is_retry=True, passed_tests=passed_tests)),
      api.post_check(PropertyEquals, 'scheduled_hw_tests',
                     expected_hw_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_vm_tests',
                     expected_tast_vm_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_gce_tests',
                     expected_tast_gce_test_names),
  )

  # Snapshot-orchestrator should only run non-informational VM tests and HW
  # tests in SNAPSHOT_HWTEST_SUITES.
  expected_hw_test_names = [
      'htarget.hw.bvt-cq',
      'htarget.hw.bvt-inline',
      'htarget.hw.some-suite',
  ]
  expected_tast_vm_test_names = [
      'ttarget.tast.sweet_shard_1_of_2',
      'ttarget.tast.sweet_shard_2_of_2',
  ]
  expected_tast_gce_test_names = [
      'ttarget.tast_gce.sweet',
  ]
  yield api.test(
      'snapshot-filter',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='snapshot-orchestrator'),
      api.properties(
          **{
              '$chromeos/cros_test_proctor':
                  ProctorProperties(snapshot_hw_test_allowlist=[
                      'bvt-cq', 'bvt-inline', 'some-suite'
                  ]),
          }),
      api.post_check(PropertyEquals, 'scheduled_hw_tests',
                     expected_hw_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_vm_tests',
                     expected_tast_vm_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_gce_tests',
                     expected_tast_gce_test_names),
  )

  # When bucket is `staging`, cros_infra_config.is_staging returns True.
  yield api.test(
      'schedule-staging-tast-vm-tests',
      api.buildbucket.ci_build(bucket='staging'),
      api.post_check(
          LogContains,
          'schedule tast vm tests',
          'json.output',
          ['staging-', '-direct-tast-vm'],
      ), api.post_check(DropExpectation))

  yield api.test(
      'split-build-targets',
      api.properties(
          ScheduleTestsProperties(is_retry=True, passed_tests=passed_tests)),
      api.properties(
          **{
              '$chromeos/cros_test_proctor':
                  ProctorProperties(skylab_task_per_build_target=True),
          }),
      api.post_check(
          MustRun,
          'schedule hardware tests.another_target.buildbucket.schedule'),
  )

  previously_failed_now_exonerable_hw_suites = [
      'htarget.hw.bvt-cq',
      'htarget.hw.some-suite',
  ]
  expected_hw_test_names = [
      'htarget.hw.bvt-inline',
      'htarget.hw.some-other-suite',
  ]
  yield api.test(
      'dont-run-now-exonerable-hw-tests',
      api.properties(
          ScheduleTestsProperties(
              is_retry=True,
              previously_failed_now_exonerable_hw_suites=previously_failed_now_exonerable_hw_suites
          )),
      api.post_check(PropertyEquals, 'scheduled_hw_tests',
                     expected_hw_test_names),
      api.post_check(
          PropertyEquals, 'test_tasks', {
              'skylab_builder_ids': ['8922054662172514000'],
              'tast_vm_tests_builder_ids':
                  ['8922054662172514001', '8922054662172514002']
          }))
  previously_failed_now_exonerable_vm_suites = [
      'ttarget.tast.sweet_shard_1_of_2',
      'ttarget.tast.sweet-informational',
  ]
  expected_tast_vm_test_names = ['ttarget.tast.sweet_shard_2_of_2']
  yield api.test(
      'dont-run-now-exonerable-vm-tests',
      api.properties(
          ScheduleTestsProperties(
              is_retry=True,
              previously_failed_now_exonerable_vm_suites=previously_failed_now_exonerable_vm_suites
          )),
      api.post_check(PropertyEquals, 'scheduled_tast_vm_tests',
                     expected_tast_vm_test_names),
      api.post_check(
          PropertyEquals, 'test_tasks', {
              'skylab_builder_ids': ['8922054662172514000'],
              'tast_vm_tests_builder_ids': ['8922054662172514001']
          }))
