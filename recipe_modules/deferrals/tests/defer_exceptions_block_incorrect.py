# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This test is exactly the same as defer_exceptions.py, except it exists to
# demonstrate that if you attempt to suppress exceptions in a large code block,
# once an exception is thrown it will not proceed. It is not currently possible
# to proceed in that manner (see https://stackoverflow.com/a/71229057).
# The preferred way to write the code in RunSteps would be in
# defer_exceptions_block.py.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/step',
    'deferrals',
]



def RunSteps(api):
  # Set up deferrals to defer.
  with api.deferrals.raise_exceptions_at_end():
    # Swallow deferrals of the next step.
    with api.deferrals.defer_exceptions():
      api.step('a failed step', ['ls'])
      # Note that this next step will not run.
      api.step('another failed step', ['ls'])  #pragma: no cover
      # Nor this one.
      api.step('a step that SHOULD HAVE HAPPENED no matter what',
               ['ls'])  #pragma: no cover


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('a failed step', retcode=1),
      api.post_check(post_process.StepFailure, 'a failed step'),
      api.post_check(post_process.DoesNotRun, 'another failed step'),
      api.post_check(post_process.DoesNotRun,
                     'a step that SHOULD HAVE HAPPENED no matter what'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
