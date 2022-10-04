# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.repo.repo import RepoProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_source',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.cros_source.configure_builder(default_main=True)
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      try:
        api.cros_source.ensure_synced_cache('http://manifest_url',
                                            cache_path_override=None)
      except ValueError:
        pass


def GenTests(api):
  yield api.cros_source.test(
      'basic', 'snapshot', api.post_check(post_process.StatusSuccess),
      api.path.exists(api.path['start_dir'].join('chromiumos_workspace')),
      api.properties(
          **
          {'$chromeos/repo': RepoProperties(disable_source_cache_health=True)}),
      api.repo.fail_repo_sync(True))
