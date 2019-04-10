# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['test_plan']


def RunSteps(api):
  api.test_plan.generate('generate plan', ['/path/to/build/json/file'])


def GenTests(api):
  test_plan = api.test_plan.example_test_plan()

  yield (api.test('basic') + api.test_plan.simulated_generate_output(
      'generate plan', test_plan))
