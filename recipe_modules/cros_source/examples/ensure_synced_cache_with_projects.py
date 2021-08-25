# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_source',
    'repo',
]

from recipe_engine import post_process


def RunSteps(api):
  api.cros_source.configure_builder(default_main=True)
  with api.cros_source.checkout_overlays_context(snapshot_mount=True), \
      api.context(cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache(projects=['chromiumos/config'])


def GenTests(api):
  yield api.test(
      'basic-success',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'))

  yield api.test(
      'basic-failure', api.repo.fail_repo_sync(True),
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StepFailure,
                     'sync cached directory.retry cache sync'))
