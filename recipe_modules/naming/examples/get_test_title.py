# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'naming',
]

PYTHON_VERSION_DEPENDENCY = 'PY2+3'

from recipe_engine import post_process


def RunSteps(api):
  api.naming.get_test_title(1234)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )
