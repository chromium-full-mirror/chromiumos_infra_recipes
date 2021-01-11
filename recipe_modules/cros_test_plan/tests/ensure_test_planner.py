# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_test_plan',
]

from recipe_engine import post_process


def RunSteps(api):
  api.cros_test_plan._ensure_test_planner()

  # Call it a second time, so that _test_planner_path is set.
  api.cros_test_plan._ensure_test_planner()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StepCommandContains,
                     'ensure test_planner.ensure_installed',
                     ['chromiumos/infra/test_planner latest']),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{"$chromeos/cros_test_plan": {
              "test_planner_cipd_ref": "foo"
          }}),
      api.post_check(post_process.StepCommandContains,
                     'ensure test_planner.ensure_installed',
                     ['chromiumos/infra/test_planner foo']),
  )
