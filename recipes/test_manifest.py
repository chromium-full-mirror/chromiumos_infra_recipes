# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verifies a repo manifest."""

import contextlib
import re

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.test_manifest import TestManifestProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cv',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_branch',
    'cros_source',
    'deferrals',
    'gerrit',
    'git',
    'repo',
    'src_state',
]


PROPERTIES = TestManifestProperties


def RunSteps(api: RecipeApi, properties: TestManifestProperties):
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
        with api.deferrals.raise_exceptions_at_end():
          yield

  with _setup():
    gerrit_changes = api.src_state.gerrit_changes

    with api.step.nest('get current project infos'):
      old_project_infos = {p.path: p.name for p in api.repo.project_infos()}

    patch_sets = []
    if gerrit_changes:
      with api.step.nest('cherry-pick gerrit changes'):
        patch_sets = api.cros_source.apply_gerrit_changes(gerrit_changes)

        # TODO(b/287692009): Remove when file additions are handled properly.
        # Check for added files as this has the potential to cause an outage.
        # Raise exception, but defer until the end so we can run other checks.
        with api.deferrals.defer_exceptions():
          with api.step.nest('check for new files') as pres:
            for patch_set in patch_sets:
              # Only check for new file in manifest repos (other patch sets
              # might be inputs to the build because of Cq-Depends).
              if patch_set.project not in ('chromeos/manifest-internal',
                                           'chromiumos/manifest'):
                continue

              project_paths = api.cros_source.find_project_paths(
                  patch_set.project, patch_set.branch)
              for project_path in project_paths:
                path = api.cros_source.workspace_path / project_path
                with api.context(cwd=path):
                  head_commit = api.git.head_commit()
                  git_show_cmd = [
                      'git', 'show', '--pretty=oneline', '--name-status',
                      head_commit
                  ]
                  result = api.step('show HEAD commit', git_show_cmd,
                                    stdout=api.raw_io.output_text())
                  pres.logs['show HEAD commit'] = str(result.stdout)
                  for line in result.stdout.strip().splitlines():
                    # An added file line starts with A followed by whitespace.
                    if re.match(r'^A\s.*', line):
                      raise api.step.StepFailure(
                          'New files cannot currently be added to the manifest repo.'
                      )

    with api.step.nest('get new project infos'):
      new_project_infos = {p.path: p.name for p in api.repo.project_infos()}
    with api.step.nest('test b/260600258 name change'):
      for project_path, project_old_name in old_project_infos.items():
        if project_path in new_project_infos and new_project_infos[
            project_path] != project_old_name:
          raise api.step.StepFailure(
              ('Project %s changed from %s to %s, '
               'but change name without changing path is not allowed.\n'
               'See b/260600258, crbug.com/gerrit/14051 for more details.') % (
                   project_path,
                   project_old_name,
                   new_project_infos[project_path],
               ))

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
    projects = sorted(set(patch_set.project for patch_set in patch_sets))
    if projects:
      project_infos = api.repo.project_infos(projects=projects)
      for project_info in project_infos:
        manifest_path = api.cros_source.workspace_path.joinpath(
            project_info.path, 'default.xml')
        branch = project_info.branch_name
        # Test cros branch on the listed projects, but only on the checked out
        # branch.
        manifest_branch = (
            api.cros_source.manifest_branch or
            api.src_state.internal_manifest.branch)
        branch_name = api.git.extract_branch(branch)
        if (branch == manifest_branch and
            not branch_name.startswith('stabilize-') and
            project_info.name in test_branch_projects and
            api.path.exists(manifest_path)):
          # Test branching with cros_branch.  See go/cros-branch.
          api.cros_branch.create_from_file(
              manifest_path, Branch(type=Branch.CUSTOM, name='test-manifest'),
              step_name='test branch_util for %s' % project_info.name,
              push=False)


def GenTests(api: RecipeTestApi):
  internal_exists = api.path.exists(
      api.src_state.workspace_path.joinpath(
          'src/chromeos/manifest-internal/default.xml'))
  common_args = [
      api.cv(run_mode=api.cv.FULL_RUN),
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
          api.src_state.workspace_path.joinpath(
              'src/chromiumos/manifest/default.xml')), *common_args)

  head_commit_no_changes = '''
M       README.md
M       _something.xml'''

  yield api.test(
      'with-manifest-internal-changes',
      api.buildbucket.try_build(project='chromeos/manifest-internal'),
      api.properties(test_branch_projects=['chromeos/manifest-internal']),
      api.override_step_data(
          'cherry-pick gerrit changes.check for new files.show HEAD commit',
          stdout=api.raw_io.output_text(head_commit_no_changes)),
      internal_exists, tests_internal, *common_args)

  yield api.test(
      'with-manifest-internal-changes-no-cros-branch',
      api.buildbucket.try_build(project='chromeos/manifest-internal'),
      api.properties(test_branch_projects=['no-tests']), internal_exists,
      no_tests_internal, *common_args)

  yield api.test(
      'with-manifest-name-only-changes',
      api.buildbucket.try_build(project='chromeos/manifest-internal'),
      api.properties(test_branch_projects=['chromeos/manifest-internal']),
      internal_exists,
      no_tests_internal,
      *common_args,
      api.repo.project_infos_step_data(
          'get new project infos', data=[
              {
                  'project': 'new-project-c',
                  'path': 'src/project-c'
              },
          ]),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  head_commit_changes = '''
M       README.md
A       _something.xml'''

  yield api.test(
      'manifest-file-added',
      api.buildbucket.try_build(project='chromeos/manifest-internal'),
      api.properties(test_branch_projects=['chromeos/manifest-internal']),
      api.override_step_data(
          'cherry-pick gerrit changes.check for new files.show HEAD commit',
          stdout=api.raw_io.output_text(head_commit_changes)),
      internal_exists,
      tests_internal,
      *common_args,
      # Ensure we exercise the whole recipe, even if we find an added file.
      api.post_check(post_process.MustRun, 'get current project infos'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE')

  yield api.test(
      'with-non-manifest-changes',
      api.buildbucket.try_build(project='chromiumos/platform2'),
      api.post_process(post_process.DropExpectation),
  )
