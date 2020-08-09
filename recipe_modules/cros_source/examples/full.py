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
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/gitiles',
    'cros_source',
    'git',
    'gerrit',
    'src_state',
    'test_util',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.cros_source.examples.full import FullProperties

PROPERTIES = FullProperties


def RunSteps(api, properties):
  _ = api.cros_source.workspace_path

  try:
    api.cros_source.find_project_paths('fake_project', 'fake_branch')
  except api.step.StepFailure:
    pass

  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache(is_staging=True)
      api.cros_source.sync_snapshot(api.buildbucket.gitiles_commit)

  commits = api.cros_source.apply_gerrit_patch_sets(
      [api.gerrit.test_api.test_patch_set()])

  archive_path = api.path['start_dir'].join('commits.tar')
  api.cros_source.create_project_commits_archive(archive_path, commits)
  projects = api.cros_source.checkout_project_commits_archive(archive_path)
  api.assertions.assertSetEqual(set(projects), {'a/b', 'a/b/c'})

  # The test.proto default for string is empty, the api returns a None
  # when this is not set.
  expected_hash = properties.expected_snapshot_isolated_hash or None
  api.assertions.assertEqual(api.cros_source.snapshot_isolated_hash,
                             expected_hash)


def GenTests(api):

  def module_properties(props):
    """Return step_test_data for CrosSourceProperties."""
    return api.properties(**{'$chromeos/cros_source': props})

  def test(name, *args, **kwargs):
    """Create a test with properties.

    Args:
      args (list): args for api.test()
      kwargs (dict): kwargs for api.test_util.test_build.  Defaults applied:
        - cq = True.
        - revision = arbitrary sha.

    Returns:
      (TestData) the build with cros_source properties included.
    """
    kwargs = kwargs or {}
    kwargs.setdefault('cq', True)
    kwargs.setdefault('revision', '2d72510e447ab60a9728aeea2362d8be2cbd7789')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)

    return api.test(name, api.test_util.test_build(**kwargs).build, *args)

  yield test('basic', api.post_check(post_process.StatusSuccess))

  yield test(
      'merge-commit-fails',
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output('commitsha1 commitsha2')),
      api.post_check(post_process.StatusFailure))

  yield test(
      'cherry-picks',
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output('commitsha1')),
      api.post_check(post_process.StatusSuccess))

  yield test(
      'with-custom-snapshot-isolate',
      module_properties(
          CrosSourceProperties(
              snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
                  isolated_hash='xxx',
                  isolate_server='http://server.com',
              ),
          )),
      api.properties(FullProperties(expected_snapshot_isolated_hash='xxx')),
      api.post_check(post_process.StatusSuccess))
