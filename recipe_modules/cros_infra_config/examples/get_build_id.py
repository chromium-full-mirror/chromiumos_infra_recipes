# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test `build_id` property in `cros_infra_config` module."""

from PB.recipe_modules.chromeos.cros_infra_config.examples.get_build_id import GetBuildIdProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/led',
    'cros_infra_config',
]

PROPERTIES = GetBuildIdProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(api.cros_infra_config.build_id,
                             properties.expected_build_id)


def GenTests(api):
  yield api.test(
      'led-run',
      api.properties(
          GetBuildIdProperties(
              expected_build_id='led_user_example.com_deadbeef',
          ), **{
              '$recipe_engine/led': {
                  'led_run_id': 'led/user_example.com/deadbeef',
              }
          }))

  yield api.test(
      'buildbcket-run',
      api.properties(
          GetBuildIdProperties(
              expected_build_id='999999999999999999',
          ), **{
              '$recipe_engine/buildbucket': {
                  'build': {
                      'id': '999999999999999999'
                  },
              }
          }))

  yield api.test('no-build-id',
                 api.properties(GetBuildIdProperties(
                     expected_build_id='',
                 )))

  yield api.test(
      'buildbucket-over-led',
      api.properties(
          GetBuildIdProperties(
              expected_build_id='888888888888888888',
          ), **{
              '$recipe_engine/buildbucket': {
                  'build': {
                      'id': '888888888888888888'
                  },
              },
              '$recipe_engine/led': {
                  'led_run_id': 'led/user_example.com/deadcafe',
              }
          }))
