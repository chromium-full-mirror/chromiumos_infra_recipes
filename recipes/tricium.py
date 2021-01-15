# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running tricium on CLs."""

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange, GitilesCommit
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/tricium',
    'depot_tools/depot_tools',
    'bot_cost',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'repo',
    'src_state',
    'workspace_util',
    'test_util',
]


def RunSteps(api):
  with api.bot_cost.build_cost_context():
    # This builder doesn't have a builder config, but we want the shared
    # handling of gitiles_commit and gerrit_changes, and enough of a config to
    # let us work.
    api.cros_infra_config.configure_builder(
        api.buildbucket.gitiles_commit,
        api.buildbucket.build.input.gerrit_changes)

    _FullCheckout(api)


def _FullCheckout(api):
  gerrit_changes = api.cros_infra_config.gerrit_changes
  is_staging = api.cros_infra_config.is_staging

  # TODO(crbug/1039875): Look at moving this code to a recipe module and using
  # that both here, and in orchestrator.determine_repo_state.
  with api.step.nest('validate inputs') as presentation:
    # If there are no gerrit_changes, we're done.
    if len(gerrit_changes) == 0:
      presentation.step_text = "No changes given:  Build is POINTLESS."
      return
    # If there is more than one gerrit_change, this recipe was invoked incorrectly,
    # as the Tricium service only passes singletons.
    if len(gerrit_changes) != 1:
      presentation.status = api.step.FAILURE
      presentation.step_text = "More than one change given."
      return

  commit = api.src_state.gerrit_changes[0]
  patch_set = None
  with api.step.nest('select patchset') as presentation:
    patch_sets = api.gerrit.fetch_patch_sets([commit], include_files=True)
    patch_sets = filter(lambda x: x.patch_set == commit.patchset, patch_sets)
    patch_set = list(patch_sets)[0]

  analyzers = [
      api.tricium.LegacyAnalyzer(
          name='ShellcheckPortage',
          package='infra/tricium/function/shellcheck',
          executable='shellcheck_tricium',
          path_filters=['*.eclass', '*.ebuild'],
          extra_args=[
              '--path_filters=*.ebuild,*.eclass',
              # ebuilds don't export variables or use a shebang (always bash).
              '--exclude=SC2148',
              '--shell=bash',
              '--enable=avoid-nullary-conditions,check-unassigned-uppercase,require-variable-braces',
          ]),
      api.tricium.LegacyAnalyzer(
          name='Shellcheck',
          package='infra/tricium/function/shellcheck',
          executable='shellcheck_tricium',
          path_filters=['*.sh'],
          extra_args=[
              '--path_filters=*.sh',
              # SC1091: Tricium doesn't include the necessary files to follow source commands.
              # SC3043: Don't warn about local in /bin/sh
              '--exclude=SC1091,SC3043',
              '--enable=avoid-nullary-conditions,check-unassigned-uppercase,require-variable-braces,quote-safe-variables',
          ]),
      api.tricium.analyzers.SPELLCHECKER,
  ]

  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    api.cros_source.ensure_synced_cache(projects=[commit.project])
    api.workspace_util.apply_changes()
    workpath = api.workspace_util.workspace_path

    with api.step.nest('get project info') as presentation:
      with api.context(cwd=workpath):
        project_infos = api.repo.project_infos([commit.project])
        project_path = None
        for project in project_infos:
          if api.git.extract_branch(project.branch,
                                    project.branch) == api.git.extract_branch(
                                        patch_set.branch, patch_set.branch):
            project_path = workpath.join(project.path)
        if not project_path:
          presentation.status = api.step.FAILURE
          presentation.step_text = 'Project for branch {} not found.'.format(
              patch_set.branch)
          return

    commit_message = api.gerrit.get_change_description(commit)
    files = patch_set.file_infos.keys()
    api.tricium.run_legacy(analyzers, project_path, files, commit_message)


def GenTests(api):

  def test_builder(**kwargs):
    """Generate a test build."""
    kwargs.setdefault('builder', 'infra-presubmit')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  changes = [
      GerritChange(change=1, project='chromium/src',
                   host='chromium-review.googlesource.com', patchset=1),
  ]

  value_dict = {
      1: {
          'change_id': '1',
          'created': '2020-10-22 18:54:00.000000000',
          'branch': 'refs/heads/master',
          'revision_info': {
              'ref': 'refs/change/foo',
              'files': {
                  "foo.ebuild": {},
                  "bar.sh": {},
              }
          },
          'patch_set': 1,
      },
  }

  yield api.test('no-changes-given', test_builder(revision=None, cq=False))

  two_changes = [
      GerritChange(change=1, project='chromium/src',
                   host='chromium-review.googlesource.com'),
      GerritChange(change=2, project='chromium/src',
                   host='chromium-review.googlesource.com'),
  ]
  yield api.test('too-many-changes', test_builder(gerrit_changes=two_changes),
                 api.post_check(post_process.StepFailure, 'validate inputs'))

  yield api.test(
      'success', test_builder(gerrit_changes=changes),
      api.repo.project_infos_step_data(
          'get project info', data=[
              dict(project='chromium/src', remote='cros-internal',
                   rrev='refs/heads/foo', upstream='refs/heads/foo'),
              dict(project='chromium/src', remote='cros-internal',
                   rrev='refs/heads/master'),
          ]),
      api.gerrit.set_gerrit_fetch_changes_response('select patchset', changes,
                                                   value_dict))

  yield api.test(
      'no-matching-project', test_builder(gerrit_changes=changes),
      api.repo.project_infos_step_data(
          'get project info', data=[
              dict(project='chromium/src', remote='cros-internal',
                   rrev='refs/heads/foo', upstream='refs/heads/foo'),
          ]), api.post_check(post_process.StepFailure, 'get project info'))
