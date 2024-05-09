# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test sync_to_gitiles_commit."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'cros_source',
    'src_state',
]


def RunSteps(api):
  api.cros_source.configure_builder(api.src_state.gitiles_commit)
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache()
    api.cros_source.sync_to_gitiles_commit(api.src_state.gitiles_commit)


def GenTests(api):
  yield api.cros_source.test(
      'basic',
      'snapshot',
      api.post_check(post_process.DoesNotRun,
                     'sync to gitiles commit.repo sync (2)'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.cros_source.test(
      'with-retry',
      'snapshot',
      api.step_data('sync to gitiles commit.repo sync', retcode=1),
      api.post_check(post_process.MustRun,
                     'sync to gitiles commit.repo sync (2)'),
      api.post_process(post_process.DropExpectation),
  )
