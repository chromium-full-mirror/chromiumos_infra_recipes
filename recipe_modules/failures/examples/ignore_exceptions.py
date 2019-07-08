# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/step',
    'failures',
]

def RunSteps(api):
  with api.failures.ignore_exceptions():
    api.step('a failed step', ['ls'])

def GenTests(api):
  yield api.test('basic') + api.step_data('a failed step', retcode=1)
