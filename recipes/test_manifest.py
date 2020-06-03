# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verifies a repo manifest."""

from PB.recipes.chromeos.test_manifest import TestManifestProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_source',
    'gerrit',
    'repo',
]

PROPERTIES = TestManifestProperties


def RunSteps(api, properties):
  build = api.buildbucket.build
  gerrit_changes = build.input.gerrit_changes

  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache()
    if gerrit_changes:
      gerrit_changes = api.cq.ordered_gerrit_changes
      with api.step.nest('cherry-pick gerrit changes'):
        patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
        api.cros_source.apply_gerrit_patch_sets(patch_sets)

    # Try to sync to the new manifest.
    projects = sorted(set(gc.project for gc in gerrit_changes))
    project_infos = api.repo.project_infos(projects=projects)
    for project_info in project_infos:
      manifest_path = api.cros_source.workspace_path.join(
          project_info.path, 'default.xml')
      if api.path.exists(manifest_path):
        with api.step.nest('try sync %s' % project_info.name):
          api.repo.sync(manifest_name=manifest_path)

        # Test `cros branch` tool for projects specified in config.
        if project_info.name in properties.test_branch_projects:
          with api.depot_tools.on_path():
            api.step('test cros branch for %s' % project_info.name, [
                'chromite/bin/cros', 'branch', '--ack-deprecation', '--root',
                api.cros_source.workspace_path, 'create',
                '--release', '--file', manifest_path, '--yes'
            ])


def GenTests(api):
  yield api.test('without-gerrit-changes')

  yield api.test(
      'with-manifest-changes',
      api.buildbucket.try_build(project='chromeos/manifest'),
      api.cq(full_run=True),
      api.path.exists(api.path['start_dir'].join(
          'chromiumos_workspace/src/chromeos/manifest/default.xml')),
  )

  yield api.test(
      'with-manifest-internal-changes',
      api.buildbucket.try_build(project='manifest-internal'),
      api.cq(full_run=True),
      api.path.exists(api.path['start_dir'].join(
          'chromiumos_workspace/src/manifest-internal/default.xml')),
      api.properties(test_branch_projects=['manifest-internal']),
  )

  yield api.test(
      'with-manifest-internal-changes-no-cros-branch',
      api.buildbucket.try_build(project='manifest-internal'),
      api.cq(full_run=True),
      api.path.exists(api.path['start_dir'].join(
          'chromiumos_workspace/src/manifest-internal/default.xml')),
  )
