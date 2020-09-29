# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'cros_infra_config',
    'recipe_engine/assertions',
    'recipe_engine/properties',
]


def RunSteps(api):
  api.assertions.assertEqual(api.cros_infra_config.current_builder_group,
                             'current-group')
  api.assertions.assertEqual(api.cros_infra_config.parent_builder_group,
                             'parent-group')
  api.assertions.assertEqual(api.cros_infra_config.target_builder_group,
                             'target-group')

  # TODO(https://crbug.com/1109276) Remove these assertions
  # Until all existing uses are gone, make sure that the legacy properties
  # are still set
  api.assertions.assertEqual(api.properties['mastername'], 'current-group')


def GenTests(api):
  yield api.test(
      'full',
      api.cros_infra_config.current_builder_group('current-group'),
      api.cros_infra_config.parent_builder_group('parent-group'),
      api.cros_infra_config.target_builder_group('target-group'),
      api.post_process(post_process.DropExpectation),
  )
