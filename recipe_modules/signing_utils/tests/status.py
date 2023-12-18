# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify methods for signing status."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'signing_utils',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

_PASSED = 'passed'
_FAILED = 'failed'
_TERMINAL_STATES = [_PASSED, _FAILED]


def RunSteps(api: RecipeApi):
  instructions = api.properties['instructions']
  status = api.signing_utils.get_status_from_instructions(instructions)
  expected_status = api.properties['expected_status']
  api.assertions.assertEqual(expected_status, status)
  if expected_status == _PASSED:
    api.assertions.assertTrue(api.signing_utils.signing_succeeded(instructions))
    api.assertions.assertTrue(api.signing_utils.is_terminal_status(status))
  elif expected_status == _FAILED:
    api.assertions.assertTrue(api.signing_utils.signing_failed(instructions))
    api.assertions.assertTrue(api.signing_utils.is_terminal_status(status))


def GenTests(api: RecipeTestApi):
  yield api.test(
      'empty-instructions',
      api.properties(instructions={}, expected_status=None),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'missing-status',
      api.properties(instructions={'status': {}}, expected_status=None),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'status-failed',
      api.properties(
          instructions={
              'status': {
                  'status': 'failed',
                  'details': 'failed for reason foo',
              }
          }, expected_status=_FAILED),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'status-succeeded',
      api.properties(
          instructions={'status': {
              'status': 'passed',
              'details': '',
          }}, expected_status=_PASSED),
      api.post_process(post_process.DropExpectation),
  )
