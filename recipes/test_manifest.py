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
    'cros_source',
    'repo',
    'src_state',
]

import contextlib

from recipe_engine import post_process
from PB.recipes.chromeos.test_manifest import TestManifestProperties
from PB.chromiumos.branch import Branch

PROPERTIES = TestManifestProperties


def RunSteps(api, properties):
  test_branch_projects = properties.test_branch_projects or [
      api.src_state.internal_manifest.project
  ]

  @contextlib.contextmanager
  def _setup():
    """Set up the various contexts, and sync source."""
    # This will set up api.src_state properties for us.
    api.cros_source.configure_builder(api.src_state.gitiles_commit)

    with api.cros_source.checkout_overlays_context():
      api.cros_source.ensure_synced_cache()
      api.cros_source.sync_to_gitiles_commit(api.src_state.gitiles_commit)
      with api.context(cwd=api.src_state.workspace_path):
        yield

  with _setup():
    gerrit_changes = api.src_state.gerrit_changes

    commits = []
    if gerrit_changes:
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
    # chromite-cq, and/or run a recipe where the configuration specifies the
    # external manifest.
    projects = sorted(set(x.patch_set.project for x in commits))
    if projects:
      project_infos = api.repo.project_infos(projects=projects)
      for project_info in project_infos:
        manifest_path = api.cros_source.workspace_path.join(
            project_info.path, 'default.xml')
        branch = project_info.branch_name
        # Test cros branch on the listed projects, but only on the checked out
        # branch.
        manifest_branch = (
            api.cros_source.manifest_branch or
            api.src_state.internal_manifest.branch)
        if (branch == manifest_branch and
            project_info.name in test_branch_projects and
            api.path.exists(manifest_path)):
          # Test branching with cros_branch.  See go/cros-branch.
          api.cros_branch.create_from_file(
              manifest_path, Branch(type=Branch.CUSTOM, name='test-manifest'),
              step_name='test branch_util for %s' % project_info.name,
              push=False)


def GenTests(api):
  internal_exists = api.path.exists(
      api.src_state.workspace_path.join(
          'src/chromeos/manifest-internal/default.xml'))
  common_args = [
      api.cq(run_mode=api.cq.FULL_RUN),
      api.post_check(post_process.DoesNotRun,
                     'test branch_util for chromiumos/manifest')
  ]
  tests_internal = api.post_check(
      post_process.MustRun, 'test branch_util for chromeos/manifest-internal')
  no_tests_internal = api.post_check(
      post_process.DoesNotRun,
      'test branch_util for chromeos/manifest-internal')

  yield api.test('without-gerrit-changes')

  yield api.test(
      'with-manifest-changes',
      api.buildbucket.try_build(project='chromiumos/manifest'),
      api.path.exists(
          api.src_state.workspace_path.join(
              'src/chromiumos/manifest/default.xml')), *common_args)

  yield api.test(
      'with-manifest-internal-changes',
      api.buildbucket.try_build(project='chromeos/manifest-internal'),
      api.properties(test_branch_projects=['chromeos/manifest-internal']),
      internal_exists, tests_internal, *common_args)

  yield api.test(
      'with-manifest-internal-changes-no-cros-branch',
      api.buildbucket.try_build(project='chromeos/manifest-internal'),
      api.properties(test_branch_projects=['no-tests']), internal_exists,
      no_tests_internal, *common_args)
