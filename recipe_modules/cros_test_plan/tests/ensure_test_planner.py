# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_test_plan',
]


def RunSteps(api):
  api.cros_test_plan._ensure_test_planner()

  # Call it a second time, so that _test_planner_path is set.
  api.cros_test_plan._ensure_test_planner()


def GenTests(api):
  yield api.test('basic')
