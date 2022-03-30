# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for signing ChromeOS images."""

DEPS = [
    'recipe_engine/step',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  with api.step.nest('noop for now step') as presentation:
    presentation.step_text = "noop signer"


def GenTests(api):
  yield api.test('basic')
