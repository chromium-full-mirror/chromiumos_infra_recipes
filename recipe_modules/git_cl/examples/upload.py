# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'git_cl',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> None:
  output = api.git_cl.upload(topic='tensorflow', reviewers=['jeff@google.com'],
                             ccs=['dean@google.com'],
                             hashtags=['foo-refactoring', 'bar-feature'],
                             send_mail=True, target_branch='HEAD', dry_run=True)
  api.assertions.assertEqual(output, b'pytorch forever')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.git_cl.output('git_cl upload', 'pytorch forever'),
      api.post_check(post_process.StatusSuccess),
  )
