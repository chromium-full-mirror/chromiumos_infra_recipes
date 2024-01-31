# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'src_state',
    'test_util',
]



def RunSteps(api):
  bb_gitiles_commit = api.buildbucket.gitiles_commit
  # Using api.src_state.gitiles_commit
  # Initial values:
  api.assertions.assertEqual(bb_gitiles_commit, api.src_state.gitiles_commit)

  # Setting api.src_state.gitiles_commit:
  new_gitiles_commit = GitilesCommit(host='host', project='project',
                                     ref='refs/heads/foo', id='SHA')

  # Setting gitiles_commit returns the new value.
  api.src_state.gitiles_commit = new_gitiles_commit
  api.assertions.assertEqual(new_gitiles_commit, api.src_state.gitiles_commit)

  # Setting it to None reverts to the original value.
  api.src_state.gitiles_commit = None
  api.assertions.assertEqual(bb_gitiles_commit, api.src_state.gitiles_commit)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
