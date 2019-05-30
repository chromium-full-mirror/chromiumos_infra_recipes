# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verifies a repo manifest."""

from PB.recipes.chromeos.test_manifest import TestManifestProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/step',
    'cros_source',
    'gerrit',
    'repo',
]

PROPERTIES = TestManifestProperties

def RunSteps(api, properties):
  projects = properties.projects or ['chromeos/manifest-internal']
  build = api.buildbucket.build
  changes = build.input.gerrit_changes

  # TODO(evanhernandez): Move this to pointless build check.
  if changes:
    with api.step.nest('check for manifest changes') as step:
      manifest_changes = [c for c in changes if c.project in projects]
      if not manifest_changes:
        step.presentation.step_text = 'no changes to manifest, exiting'
        return

      projects = list(set(mc.project for mc in manifest_changes))

      step.presentation.step_text = 'found changes to manifest, continuing'
      for change in manifest_changes:
        change_gerrit_url = api.gerrit.parse_gerrit_change_url(change)
        step.links[change_gerrit_url] = change_gerrit_url

  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):
    if changes:
      with api.step.nest('cherry-pick gerrit changes'):
        patch_sets = api.gerrit.fetch_patch_sets(changes)
        api.cros_source.apply_gerrit_patch_sets(patch_sets)

    # Try to sync to the new manifest.
    project_infos = api.repo.project_infos(projects=projects)
    for project_info in project_infos:
      with api.step.nest('try sync %s' % project_info.name):
        manifest_path = api.cros_source.workspace_path.join(
            project_info.path, 'default.xml')
        api.repo.sync(manifest_name=manifest_path)


def GenTests(api):
  yield api.test('without-gerrit-changes')

  yield api.test('without-manifest-changes') + api.buildbucket.try_build()

  yield api.test('with-manifest-changes') + api.buildbucket.try_build(
      project='chromeos/manifest-internal')
