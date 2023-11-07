# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from PB.recipe_modules.chromeos.cros_source.examples.full import FullProperties

from recipe_engine import post_process

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

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.cros_source.configure_builder()

  try:
    api.cros_source.find_project_paths('fake_project', 'fake_branch')
  except api.step.StepFailure:
    pass

  _ = api.cros_source.sync_to_manifest

  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache(is_staging=True)
      # Either checkout tip of tree, sync to a snapshot,
      # or sync to a manifest.
      api.cros_source.checkout_tip_of_tree()
      api.cros_source.sync_checkout(api.buildbucket.gitiles_commit)
      _ = api.cros_source.pinned_manifest

  # At this point should be dirty only for custom manifest cases.
  if properties.expected_snapshot_cas_digest:
    api.assertions.assertTrue(api.cros_source.is_source_dirty)
  else:
    api.assertions.assertFalse(api.cros_source.is_source_dirty)
  _ = api.cros_source.apply_gerrit_changes(
      api.src_state.gerrit_changes,
      ignore_missing_projects=properties.ignore_missing_projects)

  if api.src_state.gerrit_changes:
    api.cros_source.checkout_gerrit_change(api.src_state.gerrit_changes[0])

  # The test.proto default for string is empty, the api returns a None
  # when this is not set.
  expected_cas_digest = properties.expected_snapshot_cas_digest or None
  api.assertions.assertEqual(api.cros_source.snapshot_cas_digest,
                             expected_cas_digest)
  api.assertions.assertTrue(api.cros_source.is_source_dirty)


def GenTests(api):
  manifest_branch = 'snapshot'
  yield api.cros_source.test('basic-success', manifest_branch)

  yield api.cros_source.test(
      'basic-failure',
      manifest_branch,
      api.repo.fail_repo_sync(True),
      status='INFRA_FAILURE',
  )

  yield api.cros_source.test(
      'chrome-ref', manifest_branch,
      git_repo='https://chromium.googlesource.com/chromium/src',
      git_ref='refs/tags/93.0.4552.0')

  sync_step_name = ('sync to gitiles commit.fetch '
                    '2d72510e447ab60a9728aeea2362d8be2cbd7789:snapshot.xml')
  yield api.cros_source.test(
      'sync-to-branch', manifest_branch,
      api.step_data(sync_step_name, api.json.output({'value': ''})), cq=False,
      git_ref='refs/heads/release-R87-13505.B')

  yield api.cros_source.test(
      'merge-commit-fails',
      manifest_branch,
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.step_data('apply gerrit patch sets.git log',
                    api.raw_io.stream_output_text('commitsha1 commitsha2')),
      gerrit_changes=[
          GerritChange(host='host', project='project', change=555, patchset=3)
      ],
      status='FAILURE',
  )

  yield api.cros_source.test(
      'with-custom-snapshot-cas-success', manifest_branch,
      api.properties(FullProperties(expected_snapshot_cas_digest='xxx')),
      cros_source_properties=CrosSourceProperties(
          snapshot_cas=CrosSourceProperties.SnapshotCas(
              digest='xxx',
          ),
      ))

  yield api.cros_source.test(
      'with-custom-snapshot-cas-failure',
      manifest_branch,
      api.properties(FullProperties(expected_snapshot_cas_digest='xxx')),
      api.repo.fail_repo_sync(True),
      cros_source_properties=CrosSourceProperties(
          snapshot_cas=CrosSourceProperties.SnapshotCas(
              digest='xxx',
          ),
      ),
      status='INFRA_FAILURE',
  )

  yield api.cros_source.test(
      'enable-custom-overlays', manifest_branch,
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
        555: {
            'branch': api.src_state.default_branch,
            'files': {
                'full.xml': {
                    'status': 'M',
                    'size_delta': 0,
                    'size': 0,
                }
            },
        },
        556: {
            'branch': 'main'
        },
    }
    return api.gerrit.set_gerrit_fetch_changes_response(name, changes,
                                                        values_dict)

  def _project_data(manifest, branch_override=None):
    return {
        'project': manifest.project,
        'path': manifest.relpath,
        'remote': manifest.remote,
        'rrev': branch_override or manifest.ref,
        'upstream': branch_override or manifest.ref,
    }

  yield api.cros_source.test(
      'empty-change-to-full.xml', manifest_branch, _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.checkout branch {}.ensure manifest is pinned'.format(
              api.src_state.default_branch), data=[
                  _project_data(api.src_state.internal_manifest),
                  _project_data(api.src_state.external_manifest), {
                      'project': 'project',
                      'path': 'chromeos/project',
                      'remote': 'cros-internal'
                  }
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
          api.raw_io.stream_output_text(
              'HEAD detached at 99caf97f\n'
              'nothing to commit, working tree clean\n'), retcode=1), cq=True,
      git_repo=api.src_state.internal_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'commit-failure-full.xml',
      manifest_branch,
      _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[_project_data(api.src_state.internal_manifest)]),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]),
      api.step_data('patch manifest.git commit',
                    api.raw_io.stream_output_text('Commit failed\n'),
                    retcode=1),
      cq=True,
      git_repo=api.src_state.internal_manifest.url,
      gerrit_changes=changes,
      status='FAILURE',
  )

  yield api.cros_source.test(
      'manifest-no-changes', None,
      api.post_process(post_process.DropExpectation), cq=True,
      git_repo=api.src_state.internal_manifest.url, gerrit_changes=[
          GerritChange(host='host', project='project', change=555, patchset=3)
      ])

  yield api.cros_source.test(
      'manifest-changes-active-internal', manifest_branch,
      _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[_project_data(api.src_state.internal_manifest)]),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]), cq=True,
      git_repo=api.src_state.internal_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'manifest-changes-active-external', manifest_branch,
      api.properties(FullProperties(ignore_missing_projects=True)),
      _gerrit_return(changes),
      api.repo.project_infos_step_data(
          'patch manifest.chromiumos/manifest: apply gerrit patch sets',
          data=[_project_data(api.src_state.external_manifest)]), cq=True,
      git_repo=api.src_state.external_manifest.url, gerrit_changes=changes)

  yield api.cros_source.test(
      'internal-change-no-external', manifest_branch,
      _gerrit_return([_manifest_change(api.src_state.internal_manifest)]),
      api.post_check(post_process.MustRun,
                     'patch manifest.restore manifest patches.branch main'),
      cq=True, git_repo=api.src_state.internal_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])

  yield api.cros_source.test(
      'internal-change-no-external-branch', manifest_branch,
      _gerrit_return([_manifest_change(api.src_state.internal_manifest)],
                     values_dict={555: {
                         'branch': 'other'
                     }}),
      api.post_check(post_process.MustRun,
                     'patch manifest.checkout branch other'),
      api.post_check(post_process.MustRun,
                     'patch manifest.restore manifest patches.branch other'),
      api.repo.project_infos_step_data(
          'patch manifest.chromeos/manifest-internal: apply gerrit patch sets',
          data=[
              _project_data(api.src_state.internal_manifest,
                            branch_override='refs/heads/other')
          ]), cq=True, git_repo=api.src_state.internal_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])

  yield api.cros_source.test(
      'manifest-changes-multi-branch',
      manifest_branch,
      _gerrit_return(changes, values_dict={556: {
          'branch': 'other'
      }}),
      cq=True,
      git_repo=api.src_state.external_manifest.url,
      gerrit_changes=changes,
      status='FAILURE',
  )

  yield api.cros_source.test(
      'manifest-changes-external-full-changed',
      manifest_branch,
      _gerrit_return(
          changes, values_dict={
              556: {
                  'branch': 'main',
                  'files': {
                      'full.xml': {
                          'status': 'M',
                          'size_delta': 0,
                          'size': 0,
                      }
                  }
              }
          }),
      cq=True,
      git_repo=api.src_state.external_manifest.url,
      gerrit_changes=changes,
      status='FAILURE',
  )

  yield api.cros_source.test(
      'manifest-changes-external-not-changed', manifest_branch,
      _gerrit_return(changes, values_dict={555: {
          'branch': 'main'
      }}), cq=True, git_repo=api.src_state.external_manifest.url,
      gerrit_changes=[_manifest_change(api.src_state.internal_manifest)])

  manifest_internal_url = (
      'https://chrome-internal.googlesource.com/chromeos/manifest-versions')

  yield api.cros_source.test(
      'sync-to-manifest-gitiles', manifest_branch,
      cros_source_properties=CrosSourceProperties(
          sync_to_manifest=ManifestLocation(
              manifest_repo_url=manifest_internal_url,
              branch='release',
              manifest_file='buildspecs/91/13818.0.0.xml',
          ),
      ))

  yield api.cros_source.test(
      'sync-to-manifest-gitiles-bad-url',
      manifest_branch,
      api.post_check(post_process.StepFailure, 'sync to specified manifest'),
      cros_source_properties=CrosSourceProperties(
          sync_to_manifest=ManifestLocation(
              manifest_repo_url='https://non-existent.com/not-authorized',
              branch='release',
              manifest_file='buildspecs/91/13818.0.0.xml',
          ),
      ),
      status='FAILURE',
  )

  yield api.cros_source.test(
      'sync-to-manifest-gitiles-missing-args',
      manifest_branch,
      api.post_check(post_process.StepFailure, 'sync to specified manifest'),
      cros_source_properties=CrosSourceProperties(
          sync_to_manifest=ManifestLocation(
              manifest_repo_url='https://non-existent.com/not-authorized',
              manifest_file='buildspecs/91/13818.0.0.xml',
          ),
      ),
      status='FAILURE',
  )

  yield api.cros_source.test(
      'sync-to-manifest-gs', manifest_branch,
      cros_source_properties=CrosSourceProperties(
          sync_to_manifest=ManifestLocation(
              manifest_gs_path='gs://chromeos-manifest-versions/release/91/13818.0.0.xml'
          ),
      ))

  yield api.cros_source.test(
      'use-released-repo-on-staging',
      manifest_branch,
      api.post_process(post_process.DropExpectation),
      bucket='staging',
      experiments=['chromeos.cros_source.use_released_repo_on_staging'],
  )
