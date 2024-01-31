# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'src_state',
    'test_util',
]



def RunSteps(api):
  bb_gerrit_changes = api.buildbucket.build.input.gerrit_changes
  # Using api.src_state.gerrit_changes
  # Initial values:
  api.assertions.assertEqual(bb_gerrit_changes, api.src_state.gerrit_changes)

  # Setting api.src_state.gerrit_changes:
  new_gerrit_changes = [
      GerritChange(host='host1', project='project1', change=123, patchset=3),
      GerritChange(host='host2', project='project2', change=321, patchset=2),
  ]

  # Setting gerrit_changes works.
  api.src_state.gerrit_changes = new_gerrit_changes
  api.assertions.assertEqual(new_gerrit_changes, api.src_state.gerrit_changes)

  # Setting it to [] empties the list.
  api.src_state.gerrit_changes = []
  api.assertions.assertEqual([], api.src_state.gerrit_changes)

  # Setting it to None reverts to the original value.
  api.src_state.gerrit_changes = None
  api.assertions.assertEqual(bb_gerrit_changes, api.src_state.gerrit_changes)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
