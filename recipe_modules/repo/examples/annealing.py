# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'easy',
    'repo',
]

from google.protobuf.json_format import MessageToDict

from PB.recipe_modules.chromeos.repo.examples import common
from PB.recipe_modules.chromeos.repo.examples.annealing import (
    AnnealingProperties)

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
      init_opts['local_manifest'] = api.repo.LocalManifest(
          local_manifest['repo'], local_manifest['path'])
    sync_opts = MessageToDict(properties.sync_opts,
                              preserving_proto_field_name=True)

    projects = list(properties.projects)
    api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                    manifest_url, init_opts=init_opts,
                                    sync_opts=sync_opts, projects=projects)
    api.easy.set_properties_step(
        commit=MessageToDict(api.repo.manifest_gitiles_commit))

    manifest_data = ('<manifest></manifest>' if not properties.manifest_data
                     else properties.manifest_data.encode('utf-8'))

    with api.step.nest('sync manifests'):
      snapshot_xml = api.repo.manifest_snapshot(properties.manifest_file,
                                                test_data=manifest_data)

    manifest_diffs = api.repo.diff_remote_and_local_manifests(
        manifest_url, properties.manifest_ref, snapshot_xml,
        test_from_data=properties.from_manifest_data.encode('utf-8'))
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
  local_manifest = common.LocalManifest(
      repo='https://chrome-internal.googlesource.com/testproject1',
      path='local_manifest.xml',
  )

  yield api.test(
      'annealing',
      api.properties(AnnealingProperties(manifest_file='snapshot.xml')))

  yield api.test(
      'annealing-local-manifest',
      api.properties(
          AnnealingProperties(manifest_file='snapshot.xml'),
          init_opts=common.InitOpts(local_manifest=local_manifest)))

  yield api.test(
      'annealing-missing-FromXML',
      api.properties(AnnealingProperties(manifest_file='snapshot.xml')),
      api.step_data('diff remote and local manifest.git show', retcode=128))

  # Annealing with diffs
  from_manifest = """
    <manifest>
      <project name="NAME" path="PATH" revision="FROM_REV"/>
      <project name="NO_CHANGE" revision="NO_CHANGE_REV"/>
      <project name="DELETED" revision="REV"/>
      <project name="IGNORE" revision="FROM_REV">
        <annotation name="snapshot-mode" value="ignore-diff"/>
      </project>
    </manifest>
  """

  to_manifest = """
    <manifest>
      <project name="NAME" path="PATH" revision="TO_REV"/>
      <project name="NO_CHANGE" revision="NO_CHANGE_REV"/>
      <project name="IGNORE" revision="TO_REV">
        <annotation name="snapshot-mode" value="ignore-diff"/>
      </project>
    </manifest>
  """
  yield api.test(
      'annealing-with-changes',
      api.properties(
          AnnealingProperties(
              manifest_file='snapshot.xml', manifest_data=to_manifest,
              from_manifest_data=from_manifest, expected_manifest_diffs=[
                  common.ManifestDiff(name='NAME', path='PATH',
                                      from_rev='FROM_REV', to_rev='TO_REV')
              ])))
