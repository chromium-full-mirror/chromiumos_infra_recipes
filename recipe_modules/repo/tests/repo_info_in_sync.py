# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/properties',
    'repo',
]



def RunSteps(api):
  test_repo_info_failure = api.properties.get('test_repo_info_failure')
  api.repo.sync(repo_event_log=False,
                test_manifest_branch_state_failure=test_repo_info_failure)


def GenTests(api):
  yield api.test('Repo-info no StepFailure',
                 api.properties(test_repo_info_failure=False),
                 api.post_process(DropExpectation))
  yield api.test('Repo-info with StepFailure',
                 api.properties(test_repo_info_failure=True),
                 api.post_process(DropExpectation))
