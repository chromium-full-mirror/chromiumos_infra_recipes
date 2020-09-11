# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'cros_paygen',
]

from recipe_engine import post_process

from PB.chromiumos import common
from PB.recipe_modules.chromeos.cros_paygen.examples.config import ConfigProperties

PROPERTIES = ConfigProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(
      len(api.cros_paygen.get_builder_config(builder_name='arkham')), 1)
  api.assertions.assertEqual(
      api.cros_paygen.get_builder_config(builder_name='videogamething'), [])
  api.assertions.assertEqual(
      api.cros_paygen.get_builder_config(builder_name='amenia',
                                         delta_type='WONT_MATCH'), [])
  api.assertions.assertEqual(
      len(
          api.cros_paygen.get_builder_config(builder_name='amenia',
                                             delta_type='NO_DELTA')), 1)
  api.assertions.assertEqual(
      api.cros_paygen.default_delta_types,
      ['STEPPING_STONE', 'OMAHA', 'NO_DELTA', 'MILESTONE', 'FSI'])


def GenTests(api):
  good_json, bad_json, not_json = map(api.cros_paygen.mock_paygen,
                                      ['get paygen json.gsutil cat'] *
                                      len(api.cros_paygen.ALL_EXAMPLE_JSONS),
                                      api.cros_paygen.ALL_EXAMPLE_JSONS)

  yield api.test('basic', good_json)
  yield api.test('bad-json', bad_json, api.expect_exception('BadPaygenConfig'))
  yield api.test('not-json', not_json, api.expect_exception('ValueError'))
