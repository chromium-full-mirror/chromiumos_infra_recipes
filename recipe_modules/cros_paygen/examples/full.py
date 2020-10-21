# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_paygen',
]

from recipe_engine import post_process

from PB.chromiumos import common

from PB.recipe_modules.chromeos.cros_paygen.examples.test import TestPaygenProperties

PROPERTIES = TestPaygenProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(
      len(
          api.cros_paygen.get_builder_config(
              builder_name=properties.builder_name,
              delta_type=properties.delta_type)), properties.expected_length)

  api.assertions.assertEqual(
      api.cros_paygen.default_delta_types,
      ['STEPPING_STONE', 'OMAHA', 'NO_DELTA', 'MILESTONE', 'FSI'])

def GenTests(api):
  good_json, bad_json, not_json = map(api.cros_paygen.test_paygen,
                                      ['get paygen json.gsutil cat'] *
                                      len(api.cros_paygen.ALL_EXAMPLE_JSONS),
                                      api.cros_paygen.ALL_EXAMPLE_JSONS)

  yield api.test(
      'basic', good_json,
      api.properties(builder_name='coral', delta_type='OMAHA',
                     expected_length=2))
  yield api.test(
      'basic-miss', good_json,
      api.properties(builder_name='videogamething', expected_length=0))
  yield api.test(
      'basic-delta-miss', good_json,
      api.properties(builder_name='amenia', expected_length=0,
                     delta_type='STEPPING_STONE'))
  yield api.test(
      'basic-hit', good_json,
      api.properties(builder_name='amenia', expected_length=1,
                     delta_type='NO_DELTA'))
  yield api.test('bad-json', bad_json,
                 api.post_check(post_process.StatusFailure))
  yield api.test('not-json', not_json,
                 api.post_check(post_process.StatusFailure))
