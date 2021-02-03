# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'repo',
    'recipe_engine/path',
    'recipe_engine/assertions',
    'recipe_engine/properties',
]

from recipe_engine import post_process
from PB.recipe_modules.chromeos.repo.repo import (RepoProperties)


def RunSteps(api):
  api.assertions.assertTrue(api.repo.disable_source_cache_health)
  api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                  'http://manifest_url')


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.properties(
          **
          {'$chromeos/repo': RepoProperties(disable_source_cache_health=True)}),
  )
