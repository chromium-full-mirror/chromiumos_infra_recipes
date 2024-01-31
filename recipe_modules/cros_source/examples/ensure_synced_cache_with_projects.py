# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_source',
    'repo',
]



def RunSteps(api):
  api.cros_source.configure_builder(default_main=True)
  with api.cros_source.checkout_overlays_context(), \
      api.context(cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache(projects=['chromiumos/config'])


def GenTests(api):
  yield api.test('basic-success')

  yield api.test(
      'basic-failure',
      api.repo.fail_repo_sync(True),
      status='INFRA_FAILURE',
  )
