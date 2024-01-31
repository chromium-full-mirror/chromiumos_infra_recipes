# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'metadata_json',
    'test_util',
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
  yield api.test('basic',
                 api.test_util.test_child_build('amd64-generic', cq=True).build)
