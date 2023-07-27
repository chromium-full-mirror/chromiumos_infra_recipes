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

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  init_opts = {'manifest_branch': 'snapshot'}
  api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                  'http://manifest_url', init_opts=init_opts,
                                  sanitize=True)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/repo': RepoProperties(disable_source_cache_health=True)}),
  )
