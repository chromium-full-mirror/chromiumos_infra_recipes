# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'metadata_json',
]


def RunSteps(api):
  version_info = {
      'chromeVersion': 'version1',
      'fullVersion': 'version2',
      'platformVersion': 'version3',
      'milestoneVersion': 'version4',
  }
  api.metadata_json.add_version_entries(version_info)
  metadata = api.metadata_json.get_metadata()
  api.assertions.assertEqual(metadata['version']['chrome'], 'version1')


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='cq', builder='amd64-generic-cq'))
