# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test git_footers calls."""

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'git_footers',
]

PROPERTIES = {
    'invalid_cr_commit_position': Property(default=False)
}


def RunSteps(api, invalid_cr_commit_position):
  api.assertions.assertEqual(
      api.git_footers.from_ref('HEAD', key='Reviewed-On'),
      ['HEAD:Reviewed-On'])
  api.assertions.assertEqual(
      api.git_footers.from_message('message', key='key'),
      ['message:key'])
  api.git_footers.position_num('HEAD')

  if invalid_cr_commit_position:
    api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 1)
  else:
    api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 101)

  api.assertions.assertTrue(api.git_footers.test_api.step_data('foo', 'bar'))


def GenTests(api):
  yield api.test('basic')

  yield (
      api.test('bad-cr-commit-position') +
      api.properties(invalid_cr_commit_position=True) +
      api.step_data('read git footers (4)', retcode=1)
  )
