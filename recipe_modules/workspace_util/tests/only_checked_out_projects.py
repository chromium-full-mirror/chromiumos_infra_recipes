# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'workspace_util',
]

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api):
  changes = [
      common_pb2.GerritChange(project='chromiumos/config', change=123),
      common_pb2.GerritChange(project='privateproject1', change=456),
      common_pb2.GerritChange(project='privateproject2', change=789),
  ]

  with api.assertions.assertRaises(api.step.StepFailure):
    api.workspace_util.apply_changes(changes, name='failing apply changes')

  api.workspace_util.apply_changes(changes, only_checked_out_projects=True,
                                   name='successful apply changes')


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data(
          'failing apply changes.apply gerrit patch sets.repo forall',
          retcode=1,
          stdout=api.raw_io.output(
              'error: project chromiumos/config not found'),
      ),
      # When only_checked_out_projects is True, do a repo forall to find out
      # what repos are checked out.
      api.step_data(
          'successful apply changes.repo forall',
          stdout=api.raw_io.output(
              '\n'.join([
                  'chromiumos/config|src/config|cros|refs/heads/master',
                  'privateproject1|src/privateproject1|cros|refs/heads/master'
              ]),
          ),
      ),
      # privateproject2 was not checked out, so it's change is discarded
      api.post_process(
          post_process.StepTextEquals,
          'successful apply changes',
          'Discarded changes: 789',
      ),
      # gerrit-fetch-changes is called with changes for chromiumos/config and
      # privateproject1
      api.post_process(
          post_process.LogContains,
          'successful apply changes.gerrit-fetch-changes',
          'json.output',
          ['"change_number": 123', '"change_number": 456'],
      ),
  )
