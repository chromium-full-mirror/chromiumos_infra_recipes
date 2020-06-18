# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test git_footers calls."""

from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

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
  api.git_footers.from_gerrit_change(
      GerritChange(
          host='chromium-review.googlesource.com',
          change=91827,
          patchset=1,
      ))

  if invalid_cr_commit_position:
    api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 1)
  else:
    api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 101)

  api.assertions.assertTrue(api.git_footers.test_api.step_data('foo', 'bar'))
  api.assertions.assertTrue(
      api.git_footers.test_api.simulated_get_footers(['footer1', 'footer2']))
  api.assertions.assertTrue(
      api.git_footers.test_api.simulated_get_footers(['footer1', 'footer2'],
                                                     parent_step_name='test',
                                                     step_number=2))


def GenTests(api):
  yield api.test('basic')

  yield api.test('bad-cr-commit-position',
                 api.properties(invalid_cr_commit_position=True),
                 api.step_data('read git footers (5)', retcode=1))
