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
  test1 = FailedTestStats(test_id='test1', build_target='target1',
                          automatically_exonerated=True)
  test2 = FailedTestStats(test_id='test2', build_target='target1',
                          automatically_exonerated=True)
  test3 = FailedTestStats(test_id='test3', build_target='target1',
                          manually_exonerated=True,
                          automatically_exonerated=True)
  test4 = FailedTestStats(test_id='test1', build_target='target2',
                          automatically_exonerated=True)
  test_stats = [test1, test2, test3, test4]
  new_configs = api.exoneration_util.get_updated_configs(
      test_stats, manual_configs={})
  api.assertions.assertEqual(new_configs['test1'], ['target1', 'target2'])
  api.assertions.assertEqual(new_configs['test2'], ['target1'])
  api.assertions.assertFalse('test3' in new_configs)


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
