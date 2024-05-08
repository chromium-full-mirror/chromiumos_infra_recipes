# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_test_proctor.proctor import \
  ProctorProperties
from PB.recipe_modules.chromeos.cros_test_proctor.tests.schedule_tests import \
  ScheduleTestsProperties
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
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  _ = api.cros_test_proctor.schedule_tests(
      test_plan, list(set(properties.passed_tests)),
      properties.previously_failed_now_exonerable_hw_suites,
      api.cros_test_proctor.timeout, is_retry=properties.is_retry)


def GenTests(api):

  all_hw_test_names = [
      'htarget.hw.bvt-cq',
      'htarget.hw.bvt-inline',
      'htarget.hw.some-other-suite',
      'htarget.hw.some-suite',
  ]

  yield api.test(
      'basic',
      api.post_check(PropertyEquals, 'scheduled_hw_tests', all_hw_test_names),
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
  yield api.test(
      'retry',
      api.properties(
          ScheduleTestsProperties(is_retry=True, passed_tests=passed_tests)),
      api.post_check(PropertyEquals, 'scheduled_hw_tests',
                     expected_hw_test_names),
  )

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
              'tast_vm_tests_builder_ids': []
          }))
