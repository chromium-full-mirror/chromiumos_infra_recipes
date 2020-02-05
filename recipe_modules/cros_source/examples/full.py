# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/gitiles',
    'cros_source',
    'git',
    'gerrit',
]

from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.cros_source.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties

def RunSteps(api, properties):
  _ = api.cros_source.master_path

  try:
    api.cros_source.find_project_path('fake_project', 'fake_branch')
  except api.step.StepFailure:
    pass

  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache()
      api.cros_source.sync_snapshot(api.buildbucket.gitiles_commit)


  # Monkey-pack merge to return a StepFailure to test cherry-pick path
  def merge_fail(_a, _b, infra_step=False):
    # False means the merge failed
    return False

  api.git.merge_silent_fail = merge_fail
  commits = api.cros_source.apply_gerrit_patch_sets(
      [api.gerrit.test_api.test_patch_set()])

  archive_path = api.path['start_dir'].join('commits.tar')
  api.cros_source.create_project_commits_archive(archive_path, commits)
  projects = api.cros_source.checkout_project_commits_archive(archive_path)
  assert set(projects) == {'a/b', 'a/b/c'}, projects

  # The test.proto default for string is empty, the api returns a None
  # when this is not set.
  expected_hash = properties.expected_snapshot_isolated_hash or None
  api.assertions.assertEqual(
      api.cros_source.snapshot_isolated_hash,
      expected_hash)



def GenTests(api):
  yield api.test('basic') +  api.buildbucket.ci_build()

  yield (api.test('with-custom-snapshot-isolate') +  #
         api.properties(
             **{'$chromeos/cros_source':
                CrosSourceProperties(
                    snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
                        isolated_hash='xxx',
                        isolate_server='http://server.com',
                    ),
                )}) +  #
         api.properties(
             TestInputProperties(expected_snapshot_isolated_hash='xxx')))
