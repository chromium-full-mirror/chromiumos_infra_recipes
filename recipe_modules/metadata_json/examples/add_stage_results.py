# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'metadata_json',
]



def RunSteps(api):
  api.metadata_json.add_stage_results()
  metadata = api.metadata_json.get_metadata()
  api.assertions.assertEqual(len(metadata['results']), 2)


def GenTests(api):
  yield api.test('basic',
                 api.metadata_json.test_builder('amd64-generic', cq=True))
