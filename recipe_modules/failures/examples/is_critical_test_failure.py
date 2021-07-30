# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'failures',
]

from recipe_engine import post_process


def RunSteps(api):
  api.failures.is_critical_test_failure(1234)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusFailure),
  )
