# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the get_snapshot_builder_name function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'naming',
]


def RunSteps(api):
  result = api.naming.get_snapshot_builder_name(
      api.properties['cq_builder_name'])

  api.assertions.assertEqual(api.properties['expected_builder_name'], result)


def GenTests(api):
  yield api.test(
      'cq',
      api.properties(cq_builder_name='amd64-generic-cq',
                     expected_builder_name='amd64-generic-snapshot'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'slim-cq',
      api.properties(cq_builder_name='amd64-generic-slim-cq',
                     expected_builder_name='amd64-generic-snapshot'),
      api.post_process(post_process.DropExpectation),
  )
