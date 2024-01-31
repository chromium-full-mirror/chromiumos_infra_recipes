# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify future_utils success handler."""
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'future_utils',
]



def RunSteps(api):
  cr = api.future_utils.create_custom_response

  def success(resp):
    with api.step.nest('success handler') as pres:
      pres.step_text = '{} succeeded!'.format(resp)

  runner = api.future_utils.create_parallel_runner()
  runner.run_function_async(
      lambda req,
      _: 'response 1',
      'request 1',
      success_handler=success,
  )
  # Get responses.
  responses = runner.wait_for_and_get_responses()
  api.assertions.assertEqual(responses, [
      cr('request 1', 'response 1', 1),
  ])


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(post_process.StepTextEquals, 'success handler',
                     'response 1 succeeded!'),
      api.post_process(post_process.DropExpectation))
