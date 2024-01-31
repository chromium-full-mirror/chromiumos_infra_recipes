# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify future_utils error handling."""
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'future_utils',
]



def RunSteps(api):
  cr = api.future_utils.create_custom_response
  e = Exception('error 1 occurred')

  def func(_, _2):
    raise e

  def error(resp):
    with api.step.nest('error handler') as pres:
      pres.step_text = '{}'.format(resp)

  runner = api.future_utils.create_parallel_runner()
  runner.run_function_async(
      func,
      'request 1',
      error_handler=error,
  )
  # Get responses.
  responses = runner.wait_for_and_get_responses()
  api.assertions.assertEqual(responses, [
      cr('request 1', e, 1, True),
  ])


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(post_process.StepTextEquals, 'error handler',
                     'error 1 occurred'),
      api.post_process(post_process.DropExpectation))
