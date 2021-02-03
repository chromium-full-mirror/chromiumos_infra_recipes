# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_source',
    'repo',
    'recipe_engine/path',
    'recipe_engine/context',
    'recipe_engine/assertions',
    'recipe_engine/properties',
]

from recipe_engine import post_process
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.repo.repo import (RepoProperties)


def RunSteps(api):
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      try:
        api.cros_source.ensure_synced_cache('http://manifest_url',
                                            cache_path_override=None)
      except ValueError:
        pass


def GenTests(api):
  yield api.cros_source.test(
      'basic', api.post_check(post_process.StatusSuccess),
      api.properties(
          **
          {'$chromeos/repo': RepoProperties(disable_source_cache_health=True)}),
      api.repo.fail_repo_sync(True))
