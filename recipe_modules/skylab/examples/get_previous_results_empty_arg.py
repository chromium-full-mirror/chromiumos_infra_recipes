# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  responses = api.skylab.get_previous_results([], [])
  api.assertions.assertEqual(len(responses), 0)


def GenTests(api):
  yield api.test('basic')
