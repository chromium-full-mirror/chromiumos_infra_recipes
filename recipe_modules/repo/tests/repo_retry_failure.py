# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from PB.chromiumos.repo_cache_state import RepoState


def RunSteps(api):
  init_opts = dict(manifest_branch='snapshot')
  checkout_path = api.path['cleanup'].join('ensure')
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
  yield api.test('repo-retry-failure-unspecified', attempt_retry_repo(api, 1),
                 attempt_retry_repo(api, 2), attempt_retry_repo(api, 3),
                 api.repo.repo_current_state(RepoState.STATE_UNSPECIFIED))

  yield api.test('repo-retry-failure-clean', attempt_retry_repo(api, 1),
                 attempt_retry_repo(api, 2), attempt_retry_repo(api, 3),
                 api.repo.repo_current_state(RepoState.STATE_CLEAN))

  yield api.test('repo-retry-failure-dirty', attempt_retry_repo(api, 1),
                 attempt_retry_repo(api, 2), attempt_retry_repo(api, 3),
                 api.repo.repo_current_state(RepoState.STATE_DIRTY))

  yield api.test(
      'repo-selfupdate-failure',
      api.step_data('ensure synced checkout.repo binary update.repo selfupdate',
                    retcode=1))
