# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'exoneration_util',
]



def RunSteps(api):
  target_name = 'target1'
  test1 = FailedTestStats(build_target=target_name,
                          automatically_exonerated=True)
  test2 = FailedTestStats(build_target=target_name)
  exceeded, _ = api.exoneration_util.check_per_target_limit(
      [test1] * 4 + [test2] * 4, per_target_limit=4)
  api.assertions.assertFalse(exceeded)
  exceeded, offending_target = api.exoneration_util.check_per_target_limit(
      [test1] * 4 + [test2] * 4, per_target_limit=3)
  api.assertions.assertTrue(exceeded)
  api.assertions.assertEqual(offending_target, target_name)


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
