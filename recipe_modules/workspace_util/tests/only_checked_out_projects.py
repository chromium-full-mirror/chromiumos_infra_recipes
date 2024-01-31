# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'repo',
    'workspace_util',
]



def RunSteps(api: RecipeApi) -> None:
  changes = [
      common_pb2.GerritChange(host='chrome-internal-review.googlesource.com',
                              project='chromiumos/config', change=123),
      common_pb2.GerritChange(host='chrome-internal-review.googlesource.com',
                              project='privateproject1', change=456),
      common_pb2.GerritChange(host='chrome-internal-review.googlesource.com',
                              project='privateproject2', change=789),
  ]

  # Call setup_workspace without first calling configure_builder.
  with api.workspace_util.setup_workspace():
    with api.assertions.assertRaises(api.step.StepFailure):
      api.workspace_util.apply_changes(changes, name='failing apply changes')

  api.workspace_util.apply_changes(changes, ignore_missing_projects=True,
                                   name='successful apply changes')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.step_data(
          'failing apply changes.apply gerrit patch sets.repo forall',
          retcode=1,
          stdout=api.raw_io.output_text(
              'error: project chromiumos/config not found'),
      ),
      # When ignore_missing_projects is True, do a repo forall to find out
      # what repos are checked out.
      api.repo.project_infos_step_data(
          'successful apply changes.apply gerrit patch sets', [
              {
                  'project': 'chromiumos/config',
                  'path': 'src/config'
              },
              {
                  'project': 'privateproject1'
              },
          ]),
      # privateproject2 was not checked out, so it's change is discarded
      api.post_process(
          post_process.StepTextEquals,
          'successful apply changes.apply gerrit patch sets',
          'Discarded changes: chrome-internal:789',
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

  yield api.test(
      'all-changes-discarded',
      api.step_data(
          'failing apply changes.apply gerrit patch sets.repo forall',
          retcode=1,
          stdout=api.raw_io.output_text(
              'error: project chromiumos/config not found'),
      ),
      api.repo.project_infos_step_data(
          'successful apply changes.apply gerrit patch sets', [{
              'project': 'privateproject3'
          }]),
      # All changes were discarded.
      api.post_process(
          post_process.StepTextEquals,
          'successful apply changes.apply gerrit patch sets',
          'Discarded changes: chrome-internal:123, chrome-internal:456, chrome-internal:789',
      ),
  )
