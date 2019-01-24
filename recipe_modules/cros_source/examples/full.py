# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'cros_source',
    'gerrit',
]


def RunSteps(api):
  commits = api.cros_source.apply_gerrit_patch_sets(
      [api.gerrit.test_api.test_patch_set()])

  archive_path = api.path['start_dir'].join('commits.tar')
  api.cros_source.create_project_commits_archive(archive_path, commits)
  projects = api.cros_source.checkout_project_commits_archive(archive_path)
  assert set(projects) == {'a/b', 'a/b/c'}, projects

def GenTests(api):
  yield api.test('basic')
