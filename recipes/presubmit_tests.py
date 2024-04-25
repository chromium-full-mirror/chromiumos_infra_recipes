# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running presubmit on multiple CLs."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.presubmit_tests import PresubmitTestsProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'bot_cost',
    'cros_infra_config',
    'cros_source',
    'gerrit',
    'git',
    'gitiles',
    'repo',
    'src_state',
    'workspace_util',
    'test_util',
]


PROPERTIES = PresubmitTestsProperties

# NB: Keep in sync with mock_CLs.
REPO_PROJECTS_INFO_TEST_DATA = [
    {
        'project': 'p1'
    },
    {
        'project': 'p1'
    },
    {
        'project': 'p2'
    },
    {
        'project': 'p2',
        'upstream': 'refs/heads/dev',
        'path': 'src/p2-dev'
    },
]


def RunSteps(api: RecipeApi, properties: PresubmitTestsProperties):
  with api.bot_cost.build_cost_context():
    # This builder doesn't have a builder config, but we want the shared
    # handling of gitiles_commit and gerrit_changes, and enough of a config to
    # let us work.
    api.cros_source.configure_builder(
        api.buildbucket.gitiles_commit,
        api.buildbucket.build.input.gerrit_changes)

    _FullCheckout(api, properties)


def _FullCheckout(api: RecipeApi, properties: PresubmitTestsProperties):
  gerrit_changes = api.src_state.gerrit_changes
  is_staging = api.cros_infra_config.is_staging
  project_names = properties.project_names

  # TODO(crbug/1039875): Look at moving this code to a recipe module and using
  # that both here, and in orchestrator.determine_repo_state.
  with api.step.nest('validate inputs') as presentation:
    # If there are no gerrit_changes, we're done.
    if not gerrit_changes:
      presentation.step_text = 'No changes given:  Build is POINTLESS.'
      return

  # Some of the repos (e.g., crostools) reach into other repos in presubmit
  # checks.  As such, we grab sync the source tree.  Start with a full checkout
  # of the manifest, apply the changes, and then run presubmit checks.
  # TODO(crbug/1039875): Update this to only checkout the required repos, as
  # well as any that are listed as dependencies by the repos being tested,
  # rather than doing a full checkout every time.
  with api.workspace_util.setup_workspace(), \
      api.workspace_util.sync_to_commit(staging=is_staging):
    api.workspace_util.apply_changes()
    workpath = api.workspace_util.workspace_path

    with api.step.nest('run presubmit checks'):
      # Set up some variables that are used repeatedly in the for loop.

      # One project can map to multiple ProjectInfos.
      # For example, if a project is listed twice in the manifest under two
      # different paths will return two ProjectInfos.
      project_infos = api.repo.project_infos(
          projects=[patch.project for patch in api.workspace_util.patch_sets],
          test_data=api.repo.test_api.project_infos_test_data(
              REPO_PROJECTS_INFO_TEST_DATA))
      checked_paths = set()

      for project_info in project_infos:
        if project_info.path in checked_paths:
          continue
        checked_paths.add(project_info.path)
        full_path = workpath / project_info.path
        with api.step.nest('checking %s' % project_info.path) as presentation:
          # If we have a list of included projects, then exclude any projects
          # not on the list.
          if project_names and project_info.name not in project_names:
            presentation.step_text = 'Excluded by properties.project_names.'
            continue

          # See if any of the CLs were applied to this specific checkout.  If a
          # project has multiple branches checked out (e.g. the kernel), we only
          # want to run presubmit checks against the branches that were patched.
          # The manifest branch will be fully qualified (e.g. refs/heads/foo)
          # while the Gerrit CL will not (e.g. foo).
          if not any((x.project, x.branch) == (project_info.name,
                                               project_info.branch_name)
                     for x in api.workspace_util.patch_sets):
            presentation.step_text = 'No CLs apply to this project & branch'
            continue

          # All of the projects will have a branch defined by the manifest.
          branch = api.git.extract_branch(project_info.branch, None)
          full_path = workpath / project_info.path
          with api.context(cwd=full_path), api.depot_tools.on_path():
            # Several checks require that we have an upstream tracking branch.
            # This requires us to have a branch, which we don't yet have.
            # Create the "__presubmit" branch, run the check, and then delete
            # it.
            with api.git.head_context():
              api.step('setup', ['git', 'checkout', '-b', '__presubmit'])
              api.step('set tracking', [
                  'git', 'branch', '--set-upstream-to',
                  '%s/%s' % (project_info.remote, branch)
              ])
              api.path.mock_add_paths(full_path / properties.test_filename)
              api.step(
                  'repo presubmit',
                  [workpath / 'src/repohooks/pre-upload.py', '--pre-submit'])
            # The branch isn't merged, so we have to use -D.
            api.step('branch cleanup', ['git', 'branch', '-D', '__presubmit'])


def GenTests(api: RecipeTestApi):
  mock_CLs = [
      common_pb2.GerritChange(host='chromium.googlesource.com', project='p1',
                              change=1234),
      common_pb2.GerritChange(host='chrome-internal.googlesource.com',
                              project='p1', change=1235),
      common_pb2.GerritChange(host='chrome-internal.googlesource.com',
                              project='p2', change=2341),
      common_pb2.GerritChange(host='chrome-internal.googlesource.com',
                              project='p2', change=2999),
  ]

  def test_builder(**kwargs) -> TestData:
    """Generate a test build."""
    kwargs.setdefault('builder', 'infra-presubmit')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  yield api.test('basic', test_builder(gerrit_changes=mock_CLs))

  yield api.test('missing',
                 test_builder(builder='missing', gerrit_changes=mock_CLs))

  yield api.test('no-gitiles-given',
                 test_builder(revision=None, gerrit_changes=mock_CLs))

  yield api.test('no-changes-given', test_builder(revision=None, cq=False))

  yield api.test('excluded-change', test_builder(gerrit_changes=mock_CLs),
                 api.properties(project_names=['p1']))

  yield api.test('has-PRESUBMIT.py', test_builder(gerrit_changes=mock_CLs),
                 api.properties(test_filename='PRESUBMIT.py'))

  yield api.test('has-PRESUBMIT.cfg', test_builder(gerrit_changes=mock_CLs),
                 api.properties(test_filename='PRESUBMIT.cfg'))
