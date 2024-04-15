# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.repo.repo import RepoProperties

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'repo',
]



def RunSteps(api):
  init_opts = {'manifest_branch': 'snapshot'}
  api.repo.ensure_synced_checkout(
      api.path.cleanup_dir.join('ensure'), 'http://manifest_url',
      init_opts=init_opts)


def GenTests(api):
  yield api.repo.test(
      'basic-on',
      api.properties(
          **
          {'$chromeos/repo': RepoProperties(
              disable_source_cache_health=False)}),
  )
