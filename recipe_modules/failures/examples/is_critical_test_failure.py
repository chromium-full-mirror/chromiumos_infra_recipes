# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'failures',
]



def RunSteps(api):
  api.failures.is_critical_test_failure(1234)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
