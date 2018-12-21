# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'repo',
]


def RunSteps(api):
  api.repo.init('http://manifest_url')
  api.repo.init('http://manifest_url', manifest_branch='mybranch',
                groups=['group1', 'group2'], depth=10,
                repo_url='http://repo_url')
  api.repo.sync()
  api.repo.sync(force_sync=True, detach=True, current_branch=True, jobs=99,
                no_tags=True, optimized_fetch=True, cache_dir='/tmp/cache')
  assert api.repo.manifest_snapshot() == "TEST XML"

  snapshot_a = api.path['start_dir'].join('snapshot_a.xml')
  snapshot_b = api.path['start_dir'].join('snapshot_b.xml')
  with api.context(cwd=api.path['start_dir']):
    api.repo.diffmanifests(snapshot_a, snapshot_b)

  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))
  with api.context(cwd=repo_root.join('subdir')):
    api.repo.diffmanifests(snapshot_a, snapshot_b)


def GenTests(api):
  yield api.test('setup_repo')
