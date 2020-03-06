# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for signing ChromeOS payloads (AU deltas etc)."""

DEPS = [
    'recipe_engine/step',
]


def RunSteps(api):
  with api.step.nest('noop for now step') as presentation:
    presentation.step_text = "noop sign a payload"


def GenTests(api):
  yield api.test('basic')
