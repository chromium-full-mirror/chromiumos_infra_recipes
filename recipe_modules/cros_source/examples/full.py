# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'depot_tools/gitiles',
    'cros_source',
    'gerrit',
]


def RunSteps(api):
  _ = api.cros_source.master_path

  try:
    api.cros_source.find_project_path('fake_project', 'fake_branch')
  except api.step.StepFailure:
    pass

  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

  commits = api.cros_source.apply_gerrit_patch_sets(
      [api.gerrit.test_api.test_patch_set()])

  archive_path = api.path['start_dir'].join('commits.tar')
  api.cros_source.create_project_commits_archive(archive_path, commits)
  projects = api.cros_source.checkout_project_commits_archive(archive_path)
  assert set(projects) == {'a/b', 'a/b/c'}, projects


def GenTests(api):
  yield api.test('basic') + api.buildbucket.ci_build()
