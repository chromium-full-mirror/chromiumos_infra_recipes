# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that method get_failure has error handling."""

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'instructions': Property(default={}),
    'expected': Property(default={}),
}


def RunSteps(api, instructions, expected):
  api.assertions.assertEqual(
      expected,
      api.signing.get_failure(instructions),
  )


def GenTests(api):
  yield api.test(
      'parses-meta',
      api.properties(
          instructions={
              'status': {
                  'status': 'failed',
                  'details': 'failed for reason foo',
              }
          }, expected="failed for reason foo"),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'missing-details',
      api.properties(instructions={'status': {
          'status': 'failed',
      }}, expected=None),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'missing-status',
      api.properties(instructions={}, expected=None),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'missing-meta',
      api.properties(instructions=None, expected=None),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
