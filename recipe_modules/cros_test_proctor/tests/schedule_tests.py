# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_proctor',
    'cros_test_plan',
]

PROPERTIES = {
    'passed_tests': Property(default=[]),
    'is_retry': Property(default=False),
    'expected_tests_run_count': Property(default=7),
}


def RunSteps(api, passed_tests, is_retry, expected_tests_run_count):
  snapshot = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      ref='refs/heads/snapshot', id='deadbeef')
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  tasks = api.cros_test_proctor.schedule_tests(test_plan, set(passed_tests),
                                               api.cros_test_proctor.timeout,
                                               {}, snapshot, is_retry=is_retry)
  tests_run_count = len(tasks.skylab) + len(tasks.autotest_vm) + len(
      tasks.tast_vm)
  api.assertions.assertEqual(tests_run_count, expected_tests_run_count)


def GenTests(api):

  yield api.test('basic')

  passed_tests = [
      'htarget.hw.bvt-cq',
      'htarget.hw.some-suite',
      'ttarget.tast.sweet',
      'vtarget.vm.auto',
      'vtarget.vm.another-auto',
  ]
  expected_tests_run = ['htarget.hw.bvt-inline']

  yield api.test(
      'retry',
      api.properties(is_retry=True, passed_tests=passed_tests,
                     expected_tests_run_count=len(expected_tests_run)))

  yield api.test(
      'retry-filter',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='snapshot-orchestrator'),
      api.properties(is_retry=True, passed_tests=passed_tests,
                     expected_tests_run_count=0))
