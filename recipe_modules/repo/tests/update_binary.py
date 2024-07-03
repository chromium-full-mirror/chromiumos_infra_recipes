# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test that we update the repo binary before syncing, once per workspace."""

from typing import Generator

from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'repo',
]

_MANIFEST_URL = 'https://manifest_url.biz'


def RunSteps(api: recipe_api.RecipeApi):
  workspace1 = api.path.start_dir / 'workspace1'
  api.path.mock_add_directory(workspace1 / '.repo')
  workspace2 = api.path.start_dir / 'workspace2'
  api.path.mock_add_directory(workspace2 / '.repo')

  with api.step.nest('workspace1'), api.context(cwd=workspace1):
    api.repo.init(_MANIFEST_URL)
    api.repo.init(_MANIFEST_URL)
  with api.step.nest('workspace2'), api.context(cwd=workspace2):
    api.repo.init(_MANIFEST_URL)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'basic',
      api.post_check(post_process.MustRun, 'workspace1.repo binary update'),
      api.post_check(post_process.MustRun, 'workspace1.repo init (2)'),
      api.post_check(post_process.DoesNotRun,
                     'workspace1.repo binary update (2)'),
      api.post_check(post_process.MustRun, 'workspace2.repo binary update'),
      api.post_process(post_process.DropExpectation),
  )
