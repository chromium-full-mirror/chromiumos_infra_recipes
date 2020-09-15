# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs actions on config repos after CLs are submitted.

For example, if a src/project repo has filtered public configs, there can be an
action to copy these public configs to a public repo.

Each action is a function that takes a list of config repos to operate on and
returns a list of repos to make commits to.
"""

from collections import namedtuple
from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'cros_source',
    'gerrit',
    'git',
    'repo',
]
"""Represents a commit that should be made as the result of an action.

Fields:
  project_path (str): Path to the repo to commit to.
  message (str): Commit message.
"""
CommitInfo = namedtuple('CommitInfo', ['project_path', 'message'])


def _replicate_public_config(api, project_infos):
  """Replicates any public configs in project repos into a public repo.

  Args:
    See notes on _ACTIONS.
  """
  public_repo_path = api.context.cwd.join('src', 'project_public')

  for project_info in project_infos:
    public_config_path = api.context.cwd.join(project_info.path,
                                              'public_sw_build_config')
    api.path.mock_add_paths(public_config_path)
    if api.path.exists(public_config_path):
      # Parse the program and project name out of the project repo path. It is
      # expected that the project repo path has a format like
      # "src/project/<program>/<project>".
      #
      # The program and project names are then used to form the destination path
      # in the public repo.
      dirname, project_name = api.path.split(project_info.path)
      _, program_name = api.path.split(dirname)
      dest_path = public_repo_path.join(program_name, project_name,
                                        'sw_build_config')
      api.file.copytree('copy public config', public_config_path, dest_path)

  return [CommitInfo(public_repo_path, 'Update with filtered configs.')]


# A list of functions to run on config repos. Each action should take a
# RecipesApi and list of ProjectInfos as args and return a list of CommitInfos.
_ACTIONS = [
    _replicate_public_config,
]


def _get_config_projects(api):
  """Returns a list of ProjectInfos for all config repos."""
  return api.repo.project_infos(
      regexes=['chromeos/program', 'chromeos/project'])


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(), \
    api.context(cwd=api.cros_source.workspace_path):

    api.cros_source.ensure_synced_cache()

    with api.step.nest('find config repos'):
      config_projects = _get_config_projects(api)

    # Defer results so that a failure on one action doesn't block later actions.
    with api.step.defer_results():
      for action in _ACTIONS:

        # Use the name of the fn. to create step names, branch names, etc.
        action_name = action.__name__.strip('_')
        with api.step.nest('Do {} and create CL'.format(action_name)):
          commit_infos = action(api, config_projects)

          for commit_info in commit_infos:
            with api.context(cwd=commit_info.project_path):
              if api.git.diff_check(commit_info.project_path):
                api.repo.start(action_name, projects=[commit_info.project_path])
                api.git.add([commit_info.project_path])
                api.git.commit(commit_info.message)

                # TODO(crbug.com/1092530): Add reviewers and / or automatically
                # submit changes once this is tested.
                api.gerrit.create_change(project=commit_info.project_path)


def GenTests(api):

  def config_repos_step_data(api):
    """Returns StepData for the find config repos call."""
    return api.step_data(
        'find config repos.repo forall', stdout=api.raw_io.output(
            '\n'.join(
                '{}|{}|cros|refs/heads/main|refs/heads/main'.format(name, path)
                for name, path in [
                    ('chromeos/project/galaxy/milkyway',
                     'src/project/galaxy/milkyway'),
                    ('chromeos/program/galaxy', 'src/program/galaxy'),
                ]),
        ))

  yield api.test(
      'basic',
      config_repos_step_data(api),
      api.post_process(
          post_process.StepCommandContains,
          'Do replicate_public_config and create CL.copy public config',
          [
              'copytree',
              '[START_DIR]/chromiumos_workspace/src/project/galaxy/milkyway/public_sw_build_config',
              '[START_DIR]/chromiumos_workspace/src/project_public/galaxy/milkyway/sw_build_config',
          ],
      ),
  )
