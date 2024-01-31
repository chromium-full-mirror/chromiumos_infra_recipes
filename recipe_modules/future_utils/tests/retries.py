# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify future_utils retries."""
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'future_utils',
]



def RunSteps(api):
  cr = api.future_utils.create_custom_response
  e = Exception('error 1 occurred')

  def func(_, try_count):
    if try_count == 1:
      raise e
    return 'response 1'

  def success(resp):
    with api.step.nest('success handler') as pres:
      pres.step_text = '{} succeeded!'.format(resp)

  def error(resp):
    with api.step.nest('error handler') as pres:
      pres.step_text = '{}'.format(resp)

  runner = api.future_utils.create_parallel_runner()
  runner.run_function_async(
      func,
      'request 1',
      success_handler=success,
      error_handler=error,
      try_count=2,
  )
  # Get responses.
  responses = runner.wait_for_and_get_responses()
  api.assertions.assertEqual(responses, [
      cr('request 1', 'response 1', 2),
  ])


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(post_process.StepTextEquals, 'error handler',
                     'error 1 occurred'),
      api.post_check(post_process.StepTextEquals, 'success handler',
                     'response 1 succeeded!'),
      api.post_process(post_process.DropExpectation))
