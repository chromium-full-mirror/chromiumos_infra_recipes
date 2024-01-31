# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'repo',
]



def RunSteps(api):
  init_opts = {'manifest_branch': 'snapshot'}
  api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                  'http://manifest_url', init_opts=init_opts)


def GenTests(api):
  yield api.test(
      'repo-no-event-log-succeeds',
      api.step_data('ensure synced checkout.repo stats.event-log', retcode=1),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'repo-bad-event-log-succeeds',
      api.step_data('ensure synced checkout.repo stats.event-log',
                    api.file.read_text('not json yo')),
      api.post_process(post_process.DropExpectation),
  )
