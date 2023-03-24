# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

"""This test only exists because a util was removed from `util.py` and it was
the only thing tested. This test tricks the recipes engine into thinking there
is a test suite for this util module, despite it having no functionality other
than a single util used in some tests.
"""


def RunSteps(api):
  api.assertions.assertTrue(True)


def GenTests(api):

  yield api.test('basic', api.post_process(post_process.DropExpectation))
