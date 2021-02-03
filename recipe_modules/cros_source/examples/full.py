# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/gitiles',
    'cros_source',
    'git',
    'gerrit',
    'repo',
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
      _ = api.cros_source.pinned_manifest

  # At this point should be dirty only for custom manifest cases.
  if properties.expected_snapshot_cas_digest:
    api.assertions.assertTrue(api.cros_source.is_source_dirty)
  elif properties.expected_snapshot_isolated_hash:
    api.assertions.assertTrue(api.cros_source.is_source_dirty)
  else:
    api.assertions.assertFalse(api.cros_source.is_source_dirty)
  commits = api.cros_source.apply_gerrit_changes(
      api.src_state.gerrit_changes,
      ignore_missing_projects=properties.ignore_missing_projects)

  archive_path = api.path['start_dir'].join('commits.tar')
  api.cros_source.create_project_commits_archive(archive_path, commits)
  projects = api.cros_source.checkout_project_commits_archive(archive_path)
  api.assertions.assertSetEqual(set(projects), {'a/b', 'a/b/c'})

  # The test.proto default for string is empty, the api returns a None
  # when this is not set.
  expected_isolate_hash = properties.expected_snapshot_isolated_hash or None
  expected_cas_digest = properties.expected_snapshot_cas_digest or None
  api.assertions.assertEqual(api.cros_source.snapshot_isolated_hash,
                             expected_isolate_hash)
  api.assertions.assertEqual(api.cros_source.snapshot_cas_digest,
                             expected_cas_digest)
  api.assertions.assertTrue(api.cros_source.is_source_dirty)


def GenTests(api):

  yield api.cros_source.test('basic-success',
                             api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'basic-failure', api.repo.fail_repo_sync(True),
      api.post_check(post_process.StepFailure,
                     'sync cached directory.retry cache sync'))

  sync_step_name = ('sync to snapshot.fetch '
                    '2d72510e447ab60a9728aeea2362d8be2cbd7789:snapshot.xml')
  yield api.cros_source.test(
      'sync-to-branch', api.post_check(post_process.StatusSuccess),
      api.step_data(sync_step_name, api.json.output(dict(value=''))), cq=False,
      git_ref='refs/heads/release-R87-13505.B')

  yield api.cros_source.test(
      'merge-commit-fails',
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output('commitsha1 commitsha2')),
      api.post_check(post_process.StatusFailure), gerrit_changes=[
          GerritChange(host='host', project='project', change=555, patchset=3)
      ])

  yield api.cros_source.test(
      'cherry-picks',
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output('commitsha1')),
      api.post_check(post_process.StatusSuccess), gerrit_changes=[
          GerritChange(host='host', project='project', change=555, patchset=3)
      ])

  # TODO(b/156557792): remove isolate test after migration
  yield api.cros_source.test(
      'disallowed-custom-snapshot-isolate',
      api.properties(FullProperties(expected_snapshot_isolated_hash='xxx')),
      api.post_check(post_process.StatusAnyFailure),
      cros_source_properties=CrosSourceProperties(
          snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
              isolated_hash='xxx',
              isolate_server='http://server.com',
          ),
      ))

  # TODO(b/156557792): remove isolate test after migration
  yield api.cros_source.test(
      'with-custom-snapshot-isolate',
      api.properties(FullProperties(expected_snapshot_isolated_hash='xxx')),
      api.post_check(post_process.StatusSuccess),
      cros_source_properties=CrosSourceProperties(
          allow_snapshot_isolate=True,
          snapshot_isolate=CrosSourceProperties.SnapshotIsolate(
              isolated_hash='xxx',
              isolate_server='http://server.com',
          ),
      ))

  yield api.cros_source.test(
      'with-custom-snapshot-cas-success',
      api.properties(FullProperties(expected_snapshot_cas_digest='xxx')),
      api.post_check(post_process.StatusSuccess),
      cros_source_properties=CrosSourceProperties(
          snapshot_cas=CrosSourceProperties.SnapshotCas(
              digest='xxx',
          ),
      ))

  yield api.cros_source.test(
      'with-custom-snapshot-cas-failure',
      api.properties(FullProperties(expected_snapshot_cas_digest='xxx')),
      api.repo.fail_repo_sync(True),
      api.post_check(post_process.StepFailure,
                     'sync cached directory.retry cache sync'),
      cros_source_properties=CrosSourceProperties(
          snapshot_cas=CrosSourceProperties.SnapshotCas(
              digest='xxx',
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
      _manifest_change(api.src_state.external_manifest, change=556),
      GerritChange(
          host=api.src_state.internal_manifest.host.replace('.', '-review.', 1),
          project='chromeos/project', change=557, patchset=7),
  ]

  def _gerrit_return(changes, name='', values_dict=None):
    values_dict = values_dict or {
        555:
            dict(branch=api.src_state.default_branch,
                 files={'full.xml': dict(status='M', size_delta=0, size=0)}),
        556:
            dict(branch='main')
    }
    return api.gerrit.set_gerrit_fetch_changes_response(name, changes,
                                                        values_dict)

  def _project_data(manifest, branch_override=None):
    return dict(project=manifest.project, path=manifest.relpath,
                remote=manifest.remote, rrev=branch_override or manifest.ref,
                upstream=branch_override or manifest.ref)

  yield api.cros_source.test(
      'empty-change-to-full.xml', api.post_check(post_process.StatusSuccess),
      _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.checkout branch {}.ensure manifest is pinned'.format(
              api.src_state.default_branch), data=[
                  _project_data(api.src_state.internal_manifest),
                  _project_data(api.src_state.external_manifest),
                  dict(project='project', path='chromeos/project',
                       remote='cros-internal')
              ]),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[
              _project_data(api.src_state.internal_manifest),
              _project_data(api.src_state.external_manifest)
          ]),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]),
      api.step_data(
          'patch manifest.git commit',
          api.raw_io.stream_output('HEAD detached at 99caf97f\n'
                                   'nothing to commit, working tree clean\n'),
          retcode=1), cq=True, git_repo=api.src_state.internal_manifest.url,
      gerrit_changes=changes)

  yield api.cros_source.test(
      'commit-failure-full.xml', api.post_check(post_process.StatusAnyFailure),
      _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[_project_data(api.src_state.internal_manifest)]),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]),
      api.step_data('patch manifest.git commit',
                    api.raw_io.stream_output('Commit failed\n'),
                    retcode=1), cq=True,
      git_repo=api.src_state.internal_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-no-changes', api.post_check(post_process.StatusSuccess),
      cq=True, git_repo=api.src_state.internal_manifest.url, gerrit_changes=[
          GerritChange(host='host', project='project', change=555, patchset=3)
      ])

  yield api.cros_source.test(
      'manifest-changes-active-internal',
      api.post_check(post_process.StatusSuccess), _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[_project_data(api.src_state.internal_manifest)]),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]), cq=True,
      git_repo=api.src_state.internal_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-active-external',
      api.properties(FullProperties(ignore_missing_projects=True)),
      api.post_check(post_process.StatusSuccess), _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]), cq=True,
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'internal-change-no-external',
      _gerrit_return([_manifest_change(api.src_state.internal_manifest)]),
      api.post_check(post_process.MustRun,
                     'patch manifest.restore manifest patches.branch main'),
      api.post_check(post_process.StatusSuccess), cq=True,
      git_repo=api.src_state.internal_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])

  yield api.cros_source.test(
      'internal-change-no-external-branch',
      _gerrit_return([_manifest_change(api.src_state.internal_manifest)],
                     values_dict={555: dict(branch='other')}),
      api.post_check(post_process.MustRun,
                     'patch manifest.checkout branch other'),
      api.post_check(post_process.MustRun,
                     'patch manifest.restore manifest patches.branch other'),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[
              _project_data(api.src_state.internal_manifest,
                            branch_override='refs/heads/other')
          ]), api.post_check(post_process.StatusSuccess), cq=True,
      git_repo=api.src_state.internal_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])

  yield api.cros_source.test(
      'manifest-changes-multi-branch',
      _gerrit_return(changes, values_dict={556: dict(branch='other')}),
      api.post_check(post_process.StatusAnyFailure), cq=True,
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-external-full-changed',
      _gerrit_return(
          changes, values_dict={
              556:
                  dict(
                      branch='main', files={
                          'full.xml': dict(status='M', size_delta=0, size=0)
                      })
          }), api.post_check(post_process.StatusAnyFailure), cq=True,
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-external-not-changed',
      _gerrit_return(changes, values_dict={555: dict(branch='main')}),
      api.post_check(post_process.StatusSuccess), cq=True,
      git_repo=api.src_state.external_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])
