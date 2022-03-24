# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'repo',
]

from recipe_engine import post_process


def RunSteps(api):
  init_opts = dict(manifest_branch='snapshot')
  api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                  'http://manifest_url', init_opts=init_opts)


def GenTests(api):
  yield api.test(
      'repo_no_event_log_succeeds',
      api.step_data('ensure synced checkout.repo stats.event-log', retcode=1),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'repo_bad_event_log_succeeds',
      api.step_data('ensure synced checkout.repo stats.event-log',
                    api.file.read_text('not json yo')),
      api.post_check(post_process.StatusSuccess),
  )
