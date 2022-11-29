# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_test_proctor.proctor import ProctorProperties

from recipe_engine.post_process import DropExpectation, LogContains, MustRun, PropertyEquals, StatusSuccess
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_proctor',
    'cros_test_plan',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'passed_tests': Property(default=[]),
    'is_retry': Property(default=False),
}


def RunSteps(api, passed_tests, is_retry):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response

  _ = api.cros_test_proctor.schedule_tests(test_plan, list(set(passed_tests)),
                                           api.cros_test_proctor.timeout,
                                           snapshot, is_retry=is_retry)


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

  yield api.test(
      'basic',
      api.post_check(PropertyEquals, 'scheduled_hw_tests', all_hw_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_vm_tests',
                     all_tast_vm_test_names),
      api.post_check(PropertyEquals, 'scheduled_tast_gce_tests',
                     all_tast_gce_test_names),
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
      api.properties(is_retry=True, passed_tests=passed_tests),
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
      'htarget.hw.bvt-inline',
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
      api.properties(is_retry=True, passed_tests=passed_tests),
      api.properties(
          **{
              '$chromeos/cros_test_proctor':
                  ProctorProperties(skylab_task_per_build_target=True),
          }),
      api.post_check(
          MustRun,
          'schedule hardware tests.another_target.buildbucket.schedule'),
      api.post_check(StatusSuccess))
