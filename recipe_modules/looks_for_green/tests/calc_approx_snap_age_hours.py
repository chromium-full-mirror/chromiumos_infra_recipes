# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import datetime

from PB.recipe_modules.chromeos.looks_for_green.tests.test import \
  CalcApproxSnapAgeHoursProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/time',
    'looks_for_green',
]

PROPERTIES = CalcApproxSnapAgeHoursProperties


# Default values used in testing - '2021-02-19T00:00:00'
TEST_SEED_TIME_SECONDS = 1613692800


def RunSteps(api, properties):
  test_start_timestamp = datetime.datetime.fromisoformat(
      properties.test_start_str)
  # Test calc_approx_snap_age_hours
  approx_snap_age_hours = api.looks_for_green.calc_approx_snap_age_hours(
      test_start_timestamp)
  api.assertions.assertEqual(properties.expected_approx_snap_age_hours,
                             approx_snap_age_hours)


def GenTests(api):
  yield api.test(
      '1-min',
      api.properties(expected_approx_snap_age_hours=0,
                     test_start_str='2021-02-18T23:59:00'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      '1-hour',
      api.properties(expected_approx_snap_age_hours=1,
                     test_start_str='2021-02-18T23:00:00'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      '1-hour-59-min',
      api.properties(expected_approx_snap_age_hours=2,
                     test_start_str='2021-02-18T22:01:00'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      '6-hours-31-min',
      api.properties(expected_approx_snap_age_hours=7,
                     test_start_str='2021-02-18T17:29:00'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      '25-hours',
      api.properties(expected_approx_snap_age_hours=25,
                     test_start_str='2021-02-17T23:00:00'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.post_process(post_process.DropExpectation),
  )
