# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.repo_cache_state import RepoState

DEPS = [
    'recipe_engine/path',
    'repo',
]



def RunSteps(api):
  init_opts = {'manifest_branch': 'snapshot'}
  checkout_path = api.path.cleanup_dir.join('ensure')
  repo_state_path = checkout_path.join('.recipes_state.json')
  api.path.mock_add_paths(repo_state_path)
  api.repo.ensure_synced_checkout(checkout_path, 'http://manifest_url',
                                  init_opts=init_opts)


def attempt_retry_repo(api, attempt):
  if attempt == 1:
    step_text = 'ensure synced checkout.repo init'
    retcode = 128
  elif attempt == 2:
    step_text = 'ensure synced checkout.sleep 10 min, try repo again'
    retcode = 0
  else:
    step_text = 'ensure synced checkout.repo sync'
    retcode = 128
  return api.step_data(step_text, retcode=retcode)


def GenTests(api):
  yield api.test(
      'repo-retry-failure-unspecified',
      attempt_retry_repo(api, 1),
      attempt_retry_repo(api, 2),
      attempt_retry_repo(api, 3),
      api.repo.repo_current_state(RepoState.STATE_UNSPECIFIED),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'repo-retry-failure-clean',
      attempt_retry_repo(api, 1),
      attempt_retry_repo(api, 2),
      attempt_retry_repo(api, 3),
      api.repo.repo_current_state(RepoState.STATE_CLEAN),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'repo-retry-failure-dirty',
      attempt_retry_repo(api, 1),
      attempt_retry_repo(api, 2),
      attempt_retry_repo(api, 3),
      api.repo.repo_current_state(RepoState.STATE_DIRTY),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'repo-selfupdate-failure',
      api.step_data('ensure synced checkout.repo binary update.repo selfupdate',
                    retcode=1))
