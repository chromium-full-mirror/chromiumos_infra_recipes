# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running presubmit on multiple CLs."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'bot_cost',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'gitiles',
    'repo',
    'workspace_util',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.presubmit_tests import PresubmitTestsProperties

PROPERTIES = PresubmitTestsProperties


def RunSteps(api, properties):
  # This builder doesn't have a builder config, but we want the shared handling
  # of gitiles_commit and gerrit_changes, and enough of a config to let us work.
  api.cros_infra_config.configure_builder(
      api.buildbucket.gitiles_commit,
      api.buildbucket.build.input.gerrit_changes)

  _FullCheckout(api, properties)
  myname = api.buildbucket.build.builder.builder
  bot_size = 'medium' if 'infra-' in myname else 'large'
  api.bot_cost.set_build_cost(api.buildbucket.build.id, bot_size)


def _FullCheckout(api, properties):
  gitiles_commit = api.cros_infra_config.gitiles_commit
  gerrit_changes = api.cros_infra_config.gerrit_changes
  is_staging = api.buildbucket.build.builder.builder.startswith('staging-')
  project_names = properties.project_names

  # TODO(crbug/1039875): Look at moving this code to a recipe module and using
  # that both here, and in orchestrator.determine_repo_state.
  with api.step.nest('validate inputs') as presentation:
    # If there are no gerrit_changes, we're done.
    if not len(gerrit_changes):
      presentation.step_text = "No changes given:  Build is POINTLESS."
      return

  # Some of the repos (e.g., crostools) reach into other repos in presubmit
  # checks.  As such, we grab sync the source tree.  Start with a full checkout
  # of the manifest, apply the changes, and then run presubmit checks.
  # TODO(crbug/1039875): Update this to only checkout the required repos, as
  # well as any that are listed as dependencies by the repos being tested,
  # rather than doing a full checkout every time.
  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    api.workspace_util.sync_to_commit(staging=is_staging)
    api.workspace_util.apply_changes()
    workpath = api.workspace_util.workspace_path

    with api.step.nest('run presubmit checks'):
      # Set up some variables that are used repeatedly in the for loop.
      path_info = {
          x.path: x for x in api.repo.project_infos(
              projects=[x.project for x in api.workspace_util.patch_sets])
      }
      checked_paths = set()

      for patch, commit in zip(api.workspace_util.patch_sets,
                               api.workspace_util.commits):
        if commit.path in checked_paths:
          continue
        checked_paths.add(commit.path)
        full_path = workpath.join(commit.path)
        with api.step.nest('checking %s' % commit.path) as presentation:
          # If we have a list of included projects, then exclude any projects
          # not on the list.
          if project_names and patch.project not in project_names:
            presentation.step_text = 'Excluded by properties.project_names.'
            continue

          info = path_info[commit.path]
          branch = api.git.extract_branch(info.branch, 'master')
          with api.context(cwd=full_path), api.depot_tools.on_path():
            # Several checks require that we have an upstream tracking branch.
            # This requires us to have a branch, which we don't yet have.
            # Create the "__presubmit" branch, run the check, and then delete
            # it.
            with api.git.head_context():
              api.step('setup', ['git', 'checkout', '-b', '__presubmit'])
              api.step('set tracking', [
                  'git', 'branch', '--set-upstream-to',
                  '%s/%s' % (info.remote, branch)
              ])
              api.path.mock_add_paths(full_path.join(properties.test_filename))
              if api.path.exists(full_path.join('PRESUBMIT.cfg')):
                api.step('repo presubmit', [
                    workpath.join('src/repohooks/pre-upload.py'), '--pre-submit'
                ])
              elif api.path.exists(full_path.join('PRESUBMIT.py')):
                api.step('git cl presubmit',
                         ['git', 'cl', 'presubmit', '--verbose'])
              else:
                presentation.step_text = 'No PRESUBMIT file found.'
            # The branch isn't merged, so we have to use -D.
            api.step('branch cleanup', ['git', 'branch', '-D', '__presubmit'])


def GenTests(api):
  mock_CLs = [
      common_pb2.GerritChange(host='chromium.googlesource.com', project='p1',
                              change=1234),
      common_pb2.GerritChange(host='chrome-internal.googlesource.com',
                              project='p2', change=2341),
  ]

  def test_builder(builder='infra-presubmit', gitiles=True, changes=True):
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder=builder)
    if not gitiles:
      build.input.gitiles_commit.Clear()
    if changes:
      build.input.gerrit_changes.extend(mock_CLs)
    return api.buildbucket.build(build)

  yield api.test('basic', test_builder())

  yield api.test('missing', test_builder(builder='missing'))

  yield api.test('no-gitiles-given', test_builder(gitiles=False))

  yield api.test('no-changes-given', test_builder(gitiles=False, changes=False))

  yield api.test('excluded-change', test_builder(),
                 api.properties(project_names=['p1']))

  yield api.test(
      'no-config-gitiles',
      test_builder(builder='amd64-generic-cq', gitiles=False, changes=False))

  yield api.test('has-PRESUBMIT.py', test_builder(),
                 api.properties(test_filename='PRESUBMIT.py'))

  yield api.test('has-PRESUBMIT.cfg', test_builder(),
                 api.properties(test_filename='PRESUBMIT.cfg'))
