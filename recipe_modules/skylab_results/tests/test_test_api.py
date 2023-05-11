# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'skylab_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.skylab_results.test_api.hw_test()
  api.skylab_results.test_api.skylab_task()
  api.skylab_results.test_api.skylab_result()


def GenTests(api):
  yield api.test('basic')
