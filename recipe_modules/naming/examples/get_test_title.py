# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'naming',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.naming.get_test_title(1234)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )
