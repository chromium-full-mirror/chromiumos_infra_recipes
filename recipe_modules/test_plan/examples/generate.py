# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/json',
    'test_plan'
]

def RunSteps(api):
  # TODO(yshaul): Add build_report and dep_graph when available.
  api.test_plan.generate('generate plan', None, None)

def GenTests(api):
  yield (
      api.test('basic') +
      api.step_data('generate plan',
                    stdout=api.json.output({ 'test_plan': [] }))
  )