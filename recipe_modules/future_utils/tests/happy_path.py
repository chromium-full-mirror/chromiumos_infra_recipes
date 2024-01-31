# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify future_utils happy path."""
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'future_utils',
]



def RunSteps(api):
  cr = api.future_utils.create_custom_response
  runner = api.future_utils.create_parallel_runner(2)
  # First function.
  runner.run_function_async(
      lambda req,
      _: 'response 1',
      'request 1',
  )
  # Second function (in parallel).
  runner.run_function_async(
      lambda req,
      _: 'response 2',
      'request 2',
  )
  # Third function (will run after one of the first two completes).
  runner.run_function_async(
      lambda req,
      _: 'response 3',
      'request 3',
  )
  # Get responses.
  responses = runner.wait_for_and_get_responses()
  api.assertions.assertEqual(
      sorted(responses),
      sorted([
          cr('request 1', 'response 1', 1),
          cr('request 2', 'response 2', 1),
          cr('request 3', 'response 3', 1),
      ]))


def GenTests(api):

  yield api.test('basic', api.post_process(post_process.DropExpectation))
