# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.recipe_modules.chromeos.exonerate.exonerate import OverallTestStats

DEPS = [
    'recipe_engine/assertions',
    'exoneration_util',
]



def RunSteps(api):
  target_name = 'target1'
  test1 = FailedTestStats(build_target=target_name,
                          automatically_exonerated=True)
  test2 = FailedTestStats(build_target='different_target',
                          automatically_exonerated=True)

  # Test overall limit exceeding.
  stats = [test1] * 4 + [test2] * 3
  override_info = api.exoneration_util.override_calculation(
      stats, overall_limit=6, per_target_limit=4)
  api.assertions.assertEqual(override_info.override_reason,
                             OverallTestStats.TOO_MANY_TESTS_EXONERATED_TOTAL)

  # Test overall limit exceeding.
  stats = [test1] * 4 + [test2] * 3
  override_info = api.exoneration_util.override_calculation(
      stats, overall_limit=100, per_target_limit=3)
  api.assertions.assertEqual(
      override_info.override_reason,
      OverallTestStats.TOO_MANY_TESTS_EXONERATED_PER_TARGET)
  api.assertions.assertEqual(override_info.build_target, target_name)

  # Test no limit being crossed.
  stats = [test1] * 4 + [test2] * 3
  override_info = api.exoneration_util.override_calculation(
      stats, overall_limit=100, per_target_limit=5)
  api.assertions.assertEqual(override_info.override_reason,
                             OverallTestStats.UNSPECIFIED)


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
