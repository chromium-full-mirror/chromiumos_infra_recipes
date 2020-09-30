# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verifies a repo manifest."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_branch',
    'cros_infra_config',
    'cros_source',
    'repo',
    'src_state',
]

from PB.recipes.chromeos.test_manifest import TestManifestProperties
from PB.chromiumos.branch import Branch

PROPERTIES = TestManifestProperties


def RunSteps(api, properties):
  test_branch_projects = properties.test_branch_projects or [
      'chromeos/manifest-internal', 'chromiumos/manifest'
  ]

  # This will set up api.src_state properties for us.
  api.cros_infra_config.configure_builder()

  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):
    gitiles_commit = api.src_state.gitiles_commit
    gerrit_changes = api.src_state.gerrit_changes

    api.cros_source.ensure_synced_cache()

    # TODO(crbug/1110753): Once  $chromeos/cros_source.manifest_changes_active
    # is the default, applying the changes will switch us to the correct branch
    # of the manifest.  Until then, we ignore the branch and test against ToT,
    # which is OK, since the builder is not a verifier on any other branches.
    with api.step.nest('cherry-pick gerrit changes'):
      commits = api.cros_source.apply_gerrit_changes(gerrit_changes)

    # If we get this far, we were successful in syncing to the manifest that was
    # provided by buildbucket (generally emtpy for CQ), or builder-config (if
    # any), or manifest-internal.  re-syncing to the repo from the
    # gitiles_commit at this point only serves to remove the patches in that
    # repo, though they remain live in the copy that repo actually uses.

    # TODO(crbug/1110753): Determine what other testing should happen.  If the
    # CL stack includes non-manifest CLs, then those builders will also be
    # running with the patched manifest.  It may be sufficient to run
    # chromite-cq, and/or run a recipe (even this one...) where the
    # configuration specifies the external manifest.
    projects = sorted(set(x.patch_set.project for x in commits))
    project_infos = api.repo.project_infos(projects=projects)
    for project_info in project_infos:
      manifest_path = api.cros_source.workspace_path.join(
          project_info.path, 'default.xml')
      branch = project_info.branch
      branch = (
          branch[len('refs/heads/'):]
          if branch.startswith('refs/heads/') else branch)
      # Test cros branch on the listed projects, but only on the checked out
      # branch.
      if (branch == api.cros_source.manifest_branch and
          api.path.exists(manifest_path)):
        if project_info.name in test_branch_projects:
          # Test branching with cros_branch.  See go/cros-branch.
          api.cros_branch.create_from_file(
              manifest_path, Branch(type=Branch.CUSTOM, name='test-manifest'),
              step_name='test branch_util for %s' % project_info.name,
              push=False)

          # Test `cros branch` tool for projects specified in config.
          # TODO(crbug/1128071): Remove the test with cros branch when deleting
          # it.
          with api.depot_tools.on_path():
            api.step('test cros branch for %s' % project_info.name, [
                'chromite/bin/cros', 'branch', '--ack-deprecation', '--root',
                api.cros_source.workspace_path, 'create', '--release', '--file',
                manifest_path, '--yes'
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
