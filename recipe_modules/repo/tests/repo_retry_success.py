# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'repo',
]


def RunSteps(api):
  init_opts = dict(manifest_branch='snapshot')
  api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                  'http://manifest_url', init_opts=init_opts)


def attempt_retry_repo(api, attempt):
  if attempt == 1:
    step_text = 'ensure synced checkout.repo init'
    retcode = 128
  else:
    step_text = 'ensure synced checkout.sleep 10 min, try repo again'
    retcode = 0
  return api.step_data(step_text, retcode=retcode)


def GenTests(api):
  yield api.test(
      'repo_retry_success',
      attempt_retry_repo(api, 1),
      attempt_retry_repo(api, 2),
      api.properties(**{'$chromeos/repo': {
          "remove_manifests_git": True
      }}),
  )
