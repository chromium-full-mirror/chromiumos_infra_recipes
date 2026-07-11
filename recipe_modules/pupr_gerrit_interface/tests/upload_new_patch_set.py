# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that upload_new_patch_set() runs the expected process."""

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api


DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'pupr_gerrit_interface',
]


def RunSteps(api: recipe_api.RecipeApi):
  if api.properties.get('mock_chrome_exists'):
    api.path.mock_add_paths(api.path.start_dir / 'chrome' / 'src')

  patch_set = PatchSet({
      'host': 'http://foo.com',
      'info': {
          '_number': 1234,
          'project': api.properties.get('project', 'a-project'),
      },
      'patch_set_revision': 'f000' * 10,
      'revision_info': {
          '_number': 5678,
      },
  })
  api.pupr_gerrit_interface.upload_new_patch_set(patch_set)


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(project='a-project'),
      api.post_check(post_process.StepSuccess,
                     'upload patch set for Change-Id 1234.git_cl upload'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'chrome-fallback',
      api.properties(project='chromium/src', mock_chrome_exists=True),
      api.post_check(post_process.StepSuccess,
                     'upload patch set for Change-Id 1234.git_cl upload'),
      api.post_process(post_process.DropExpectation),
  )
