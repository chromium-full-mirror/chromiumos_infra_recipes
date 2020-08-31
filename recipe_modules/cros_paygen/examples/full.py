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
EXAMPLE_PAYGEN_JSON = """
{
  "delta": [
      {
        "board": {
          "public_codename": "amenia",
          "is_active": false,
          "builder_name": "amenia"
        },
        "delta_type": "NO_DELTA",
        "generate_delta": false,
        "delta_payload_tests": false,
        "full_payload_tests": false
      },
      {
        "board": {
          "public_codename": "arkham",
          "is_active": true,
          "builder_name": "arkham"
        },
        "delta_type": "NO_DELTA",
        "generate_delta": false,
        "delta_payload_tests": false,
        "full_payload_tests": false
      }
  ]
}
"""
EXAMPLE_EMPTY_JSON = "{}"
EXAMPLE_NOT_EVEN_JSON = "dawiojdoiawjdioawjdow"


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


def GenTests(api):

  def mock_paygen_json(in_json):
    """Mock up step results for the GS cat."""
    mock_response = api.step_data('gsutil cat',
                                  stdout=api.raw_io.output(in_json))
    return mock_response

  yield api.test('basic', mock_paygen_json(EXAMPLE_PAYGEN_JSON))
  yield api.test('bad-json', mock_paygen_json(EXAMPLE_EMPTY_JSON),
                 api.expect_exception('BadPaygenConfig'))
  yield api.test('not-json', mock_paygen_json(EXAMPLE_NOT_EVEN_JSON),
                 api.expect_exception('ValueError'))
