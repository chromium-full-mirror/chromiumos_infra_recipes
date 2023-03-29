# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Generator
from typing import Optional

from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'git_cl',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'expected_output':
        Property(kind=bytes, help='Expected command output', default=''),
    'use_local_diff':
        Property(
            kind=bool,
            help='Whether to upload local diff instead of tip-of-branch diff',
            default=False),
    'message':
        Property(kind=str, help='Message for the patchset', default=None),
}


def RunSteps(api: RecipeApi, expected_output: bytes, use_local_diff: bool,
             message: Optional[str]) -> None:
  output = api.git_cl.upload(topic='tensorflow', reviewers=['jeff@google.com'],
                             ccs=['dean@google.com'],
                             hashtags=['foo-refactoring', 'bar-feature'],
                             send_mail=True, target_branch='HEAD', dry_run=True,
                             use_local_diff=use_local_diff, message=message)
  api.assertions.assertEqual(output, expected_output)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.git_cl.output('git_cl upload', 'pytorch forever'),
      api.properties(expected_output=b'pytorch forever'),
  )
  yield api.test(
      'local-diff',
      api.properties(use_local_diff=True, expected_output=b'success'),
      api.git_cl.output('git_cl upload', 'success'),
      api.post_check(post_process.StepCommandContains, 'git_cl upload',
                     ['HEAD~', 'HEAD']),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'message',
      api.properties(use_local_diff=True, expected_output=b'success',
                     message='the second patchset'),
      api.git_cl.output('git_cl upload', 'success'),
      api.post_check(post_process.StepCommandContains, 'git_cl upload',
                     ['--message', 'the second patchset']),
      api.post_process(post_process.DropExpectation),
  )
