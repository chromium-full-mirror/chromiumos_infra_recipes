# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'metadata_json',
]



def RunSteps(api):
  api.metadata_json.add_default_entries()
  metadata = api.metadata_json.get_metadata()
  api.assertions.assertEqual(metadata['builder-name'], 'amd64-generic-cq')


def GenTests(api):

  yield api.test('basic',
                 api.metadata_json.test_builder('amd64-generic', cq=True))

  # The build_id below must match the build_id used for led launched jobs in
  # api.py.
  yield api.test(
      'led',
      api.properties(
          **{'$recipe_engine/led': {
              'led_run_id': 'chromeos/led/email/hash'
          }}),
      api.metadata_json.test_builder('amd64-generic', cq=True,
                                     build_id=api.metadata_json.led_build_id),
  )
