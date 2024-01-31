# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from textwrap import dedent

from google.protobuf.json_format import MessageToDict
from PB.chromiumos.repo_cache_state import RepoState
from PB.recipe_modules.chromeos.repo.examples import common
from PB.recipe_modules.chromeos.repo.examples.annealing import AnnealingProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'easy',
    'repo',
]

PROPERTIES = AnnealingProperties


# This example shows the normal flow of events for build_menu.


def RunSteps(api, properties):
  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  with api.context(cwd=repo_root.join('manifest-internal')):
    init_opts = MessageToDict(properties.init_opts,
                              preserving_proto_field_name=True)
    manifest_url = init_opts.pop('manifest_url', 'http://manifest_url')
    local_manifest = init_opts.pop('local_manifest', None)
    if local_manifest:
      init_opts['local_manifests'] = [
          api.repo.LocalManifest(local_manifest['repo'], local_manifest['path'],
                                 init_opts.get('manifest_branch'))
      ]
    sync_opts = MessageToDict(properties.sync_opts,
                              preserving_proto_field_name=True)

    projects = list(properties.projects)
    checkout_path = api.path['cleanup'].join('ensure')
    repo_state_path = checkout_path.join('.recipes_state.json')
    api.path.mock_add_paths(repo_state_path)
    api.repo.ensure_synced_checkout(checkout_path, manifest_url,
                                    init_opts=init_opts, sync_opts=sync_opts,
                                    projects=projects)
    api.easy.set_properties_step(
        commit=MessageToDict(api.repo.manifest_gitiles_commit))

    manifest_data = ('<manifest></manifest>' if not properties.manifest_data
                     else properties.manifest_data.encode('utf-8'))

    with api.step.nest('sync manifests'):
      snapshot_xml = api.repo.manifest(properties.manifest_file, pinned=True,
                                       test_data=manifest_data)

    # Annealing passes use_merge_base=True when not publishing uprevs.
    manifest_diffs = api.repo.diff_remote_and_local_manifests(
        manifest_url, properties.manifest_ref, snapshot_xml,
        test_from_data=properties.from_manifest_data.encode('utf-8'),
        use_merge_base=True)
    expected = [
        api.repo.ManifestDiff(x.name, x.path, x.from_rev, x.to_rev)
        for x in properties.expected_manifest_diffs
    ]
    api.assertions.assertEqual(expected, manifest_diffs or [])

    # Show the output of `repo diffmanifests`.
    api.repo.diff_manifests_informational(
        repo_root.join('manifest-internal/snapshot-a.xml'),
        repo_root.join('manifest-internal/snapshot-b.xml'))


def GenTests(api):
  manifest_branch = 'snapshot'

  def AnnealingTest(state_name, state):
    return api.test(
        'annealing-{}'.format(state_name),
        api.properties(
            AnnealingProperties(
                manifest_file='snapshot.xml',
                init_opts=common.InitOpts(manifest_branch=manifest_branch))),
        api.repo.repo_current_state(state))

  def AnnealingLocalManifest(state_name, state):
    local_manifest = common.LocalManifest(
        repo='https://chrome-internal.googlesource.com/testproject1',
        path='local_manifest.xml',
    )
    return api.test(
        'annealing-local-manifest-{}'.format(state_name),
        api.properties(
            AnnealingProperties(
                manifest_file='snapshot.xml',
                init_opts=common.InitOpts(local_manifest=local_manifest,
                                          manifest_branch=manifest_branch))),
        api.repo.repo_current_state(state))

  def AnnealingMissingFromXML(state_name, state):
    return api.test(
        'annealing-missing-FromXML-{}'.format(state_name),
        api.properties(
            AnnealingProperties(
                manifest_file='snapshot.xml',
                init_opts=common.InitOpts(manifest_branch=manifest_branch))),
        api.step_data('diff remote and local manifest.git show', retcode=128),
        api.repo.repo_current_state(state))

  def AnnealingWithChanges(state_name, state):
    # Annealing with diffs
    from_manifest = '''
      <manifest>
        <default revision="refs/heads/main" remote="REMOTE" sync-j="8"/>
        <project name="NAME" path="PATH" revision="FROM_REV"/>
        <project name="NO_CHANGE" revision="NO_CHANGE_REV"/>
        <project name="DELETED" revision="REV"/>
        <project name="IGNORE" revision="FROM_REV">
          <annotation name="snapshot-mode" value="ignore-diff"/>
        </project>
      </manifest>
    '''

    to_manifest = '''
      <manifest>
        <default revision="refs/heads/main" remote="REMOTE" sync-j="8"/>
        <project name="NAME" path="PATH" revision="TO_REV"/>
        <project name="NO_CHANGE" revision="NO_CHANGE_REV"/>
        <project name="IGNORE" revision="TO_REV">
          <annotation name="snapshot-mode" value="ignore-diff"/>
        </project>
      </manifest>
    '''
    from_manifest = dedent(from_manifest)
    to_manifest = dedent(to_manifest)
    return api.test(
        'annealing-with-changes-{}'.format(state_name),
        api.step_data(
            'diff remote and local manifest.validate PATH.git merge-base',
            retcode=1),
        api.step_data('diff remote and local manifest.validate PATH.git fetch',
                      retcode=1),
        api.properties(
            AnnealingProperties(
                init_opts=common.InitOpts(manifest_branch=manifest_branch),
                manifest_file='snapshot.xml', manifest_data=to_manifest,
                from_manifest_data=from_manifest, expected_manifest_diffs=[
                    common.ManifestDiff(name='NAME', path='PATH',
                                        from_rev='FROM_REV', to_rev='TO_REV')
                ])), api.repo.repo_current_state(state))

  yield AnnealingTest('unspecified', RepoState.STATE_UNSPECIFIED)
  yield AnnealingTest('clean', RepoState.STATE_CLEAN)
  yield AnnealingTest('dirty', RepoState.STATE_DIRTY)
  yield AnnealingTest('recovery', RepoState.STATE_RECOVERY)

  yield AnnealingLocalManifest('unspecified', RepoState.STATE_UNSPECIFIED)
  yield AnnealingLocalManifest('clean', RepoState.STATE_CLEAN)
  yield AnnealingLocalManifest('dirty', RepoState.STATE_DIRTY)
  yield AnnealingLocalManifest('recovery', RepoState.STATE_RECOVERY)

  yield AnnealingMissingFromXML('unspecified', RepoState.STATE_UNSPECIFIED)
  yield AnnealingMissingFromXML('clean', RepoState.STATE_CLEAN)
  yield AnnealingMissingFromXML('dirty', RepoState.STATE_DIRTY)
  yield AnnealingMissingFromXML('recovery', RepoState.STATE_RECOVERY)

  yield AnnealingWithChanges('unspecified', RepoState.STATE_UNSPECIFIED)
  yield AnnealingWithChanges('clean', RepoState.STATE_CLEAN)
  yield AnnealingWithChanges('dirty', RepoState.STATE_DIRTY)
  yield AnnealingWithChanges('recovery', RepoState.STATE_RECOVERY)
