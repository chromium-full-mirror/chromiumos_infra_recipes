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

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.cros_source.examples.full import FullProperties

PROPERTIES = FullProperties


def RunSteps(api, properties):
  # This is normally done by cros_infra_config.configure_builder().
  if (api.buildbucket.build.input.gitiles_commit.host ==
      api.src_state.internal_manifest.host):
    api.src_state.build_manifest = api.src_state.internal_manifest
  elif (api.buildbucket.build.input.gitiles_commit.host ==
        api.src_state.external_manifest.host):
    api.src_state.build_manifest = api.src_state.external_manifest
  _ = api.cros_source.workspace_path

  try:
    api.cros_source.find_project_paths('fake_project', 'fake_branch')
  except api.step.StepFailure:
    pass

  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache(is_staging=True)
      api.cros_source.sync_snapshot(api.buildbucket.gitiles_commit)

  # At this point should be dirty only for custom manifest cases.
  if properties.expected_snapshot_isolated_hash:
    api.assertions.assertTrue(api.cros_source.is_source_dirty)
  else:
    api.assertions.assertFalse(api.cros_source.is_source_dirty)

  _ = api.cros_source.make_manifest_changes_active
  commits = api.cros_source.apply_gerrit_changes(api.src_state.gerrit_changes)

  archive_path = api.path['start_dir'].join('commits.tar')
  api.cros_source.create_project_commits_archive(archive_path, commits)
  projects = api.cros_source.checkout_project_commits_archive(archive_path)
  api.assertions.assertSetEqual(set(projects), {'a/b', 'a/b/c'})

  # The test.proto default for string is empty, the api returns a None
  # when this is not set.
  expected_hash = properties.expected_snapshot_isolated_hash or None
  api.assertions.assertEqual(api.cros_source.snapshot_isolated_hash,
                             expected_hash)
  api.assertions.assertTrue(api.cros_source.is_source_dirty)


def GenTests(api):

  yield api.cros_source.test('basic',
                             api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'merge-commit-fails',
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output('commitsha1 commitsha2')),
      api.post_check(post_process.StatusFailure))

  yield api.cros_source.test(
      'cherry-picks',
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output('commitsha1')),
      api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'with-custom-snapshot-isolate',
      api.properties(FullProperties(expected_snapshot_isolated_hash='xxx')),
      api.post_check(post_process.StatusSuccess),
      cros_source_properties=CrosSourceProperties(
          snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
              isolated_hash='xxx',
              isolate_server='http://server.com',
          ),
      ))

  yield api.cros_source.test(
      'enable-custom-overlays', api.post_check(post_process.StatusSuccess),
      cros_source_properties=CrosSourceProperties(
          enable_custom_overlays=True,
      ))

  def _manifest_change(man, change=555, patchset=3):
    return GerritChange(
        host=man.host.replace('.', '-review.', 1), project=man.project,
        change=change, patchset=patchset)

  changes = [
      _manifest_change(api.src_state.internal_manifest),
      _manifest_change(api.src_state.external_manifest, change=556)
  ]

  def _gerrit_return(changes, name='', values_dict=None):
    values_dict = values_dict or {
        555: dict(files={'full.xml': dict(status='M', size_delta=0, size=0)})
    }
    return api.gerrit.set_gerrit_fetch_changes_response(name, changes,
                                                        values_dict)

  yield api.cros_source.test(
      'manifest-no-changes', api.post_check(post_process.StatusSuccess),
      cq=True, git_repo=api.src_state.internal_manifest.url, gerrit_changes=[
          GerritChange(host='host', project='project', change=555, patchset=3)
      ], cros_source_properties=CrosSourceProperties(
          make_manifest_changes_active=True))

  yield api.cros_source.test(
      'manifest-changes-active-internal',
      api.post_check(post_process.StatusSuccess), _gerrit_return(changes),
      cq=True, git_repo=api.src_state.internal_manifest.url,
      cros_source_properties=CrosSourceProperties(
          make_manifest_changes_active=True), gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-active-external',
      api.post_check(post_process.StatusSuccess), _gerrit_return(changes),
      cq=True, cros_source_properties=CrosSourceProperties(
          make_manifest_changes_active=True),
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-multi-branch',
      _gerrit_return(changes, values_dict={556: dict(branch='other')}),
      api.post_check(post_process.StatusAnyFailure), cq=True,
      cros_source_properties=CrosSourceProperties(
          make_manifest_changes_active=True),
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-external-full-changed',
      _gerrit_return(
          changes, values_dict={
              556:
                  dict(files={
                      'full.xml': dict(status='M', size_delta=0, size=0)
                  })
          }), api.post_check(post_process.StatusAnyFailure), cq=True,
      cros_source_properties=CrosSourceProperties(
          make_manifest_changes_active=True),
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-external-not-changed',
      _gerrit_return(changes, values_dict={555: dict(branch='main')}),
      api.post_check(post_process.StatusAnyFailure), cq=True,
      cros_source_properties=CrosSourceProperties(
          make_manifest_changes_active=True),
      git_repo=api.src_state.external_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])
