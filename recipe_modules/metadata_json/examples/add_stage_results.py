# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'metadata_json',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.metadata_json.add_stage_results()
  metadata = api.metadata_json.get_metadata()
  api.assertions.assertEqual(len(metadata['results']), 2)


def GenTests(api):
  yield api.test('basic',
                 api.metadata_json.test_builder('amd64-generic', cq=True))
