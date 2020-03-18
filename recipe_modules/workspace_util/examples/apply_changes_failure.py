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

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api):
  changes = [
      common_pb2.GerritChange(change=1234),
      common_pb2.GerritChange(change=5678),
  ]

  api.assertions.assertRaises(api.step.StepFailure,
                              api.workspace_util.apply_changes, changes)

  with api.assertions.assertRaisesRegexp(api.step.StepFailure,
                                         'Failed to apply patch sets.'):
    api.workspace_util.apply_changes(changes, cq_depend_fail_message=True)

def GenTests(api):
  yield (api.test('basic') +  #
         api.step_data(
             'cherry-pick gerrit changes.apply gerrit patch sets.repo forall',
             retcode=1,
             stdout=api.raw_io.output(
                 'error: project chromiumos/config not found')) +  #
         api.step_data(
             'cherry-pick gerrit changes (2)'
             '.apply gerrit patch sets.repo forall',
             retcode=1,
             stdout=api.raw_io.output(
                 'error: project chromiumos/config not found')))
