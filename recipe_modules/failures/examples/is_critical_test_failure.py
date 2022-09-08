# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'failures',
]

from recipe_engine import post_process

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.failures.is_critical_test_failure(1234)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )
