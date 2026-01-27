# -*- coding: utf-8 -*-
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the greenness_markdown property."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'greenness',
    'test_util',
]


def RunSteps(api):
  # Initially it should be None
  api.assertions.assertIsNone(api.greenness.greenness_markdown)

  builds = [
      api.test_util.test_api.test_child_build(builder='eve-snapshot',
                                              build_target_name='eve',
                                              critical='YES',
                                              status='SUCCESS').message
  ]
  api.greenness.update_build_info(builds)
  api.greenness.print_step()

  # After print_step (which calls publish_step), it should be set
  api.assertions.assertIsNotNone(api.greenness.greenness_markdown)
  api.assertions.assertEqual(
      'Overall Greenness Score: 100, Build Only Greenness Score: 100',
      api.greenness.greenness_markdown)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{'$chromeos/greenness': {
          'publish_property': True
      }}),
      api.post_process(post_process.DropExpectation),
  )
