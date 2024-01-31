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
  test1 = FailedTestStats(automatically_exonerated=True)
  api.assertions.assertFalse(
      api.exoneration_util.check_overall_limit([test1] * 4, overall_limit=4))
  api.assertions.assertTrue(
      api.exoneration_util.check_overall_limit([test1] * 4, overall_limit=3))


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
