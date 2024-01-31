# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This test is the preferred way to write the code in
# defer_exceptions_block_incorrect.py.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/step',
    'deferrals',
]



def RunSteps(api):
  with api.deferrals.raise_exceptions_at_end():
    with api.deferrals.defer_exceptions():
      api.step('a failed step', ['ls'])
    with api.deferrals.defer_exceptions():
      api.step('another failed step', ['ls'])
    api.step('a step that should happen no matter what', ['ls'])


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('a failed step', retcode=1),
      api.step_data('another failed step', retcode=1),
      api.step_data('a step that should happen no matter what'),
      api.post_check(post_process.StepFailure, 'a failed step'),
      api.post_check(post_process.StepFailure, 'another failed step'),
      api.post_check(post_process.StepSuccess,
                     'a step that should happen no matter what'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
