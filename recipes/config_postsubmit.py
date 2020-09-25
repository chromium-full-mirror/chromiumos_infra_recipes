# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run miscellaneous actions on project repos.

Runs on a schedule rather than as a triggered/CQ action, so there is some
latency between commits landing and this script executing its tasks.

For example, if a src/project repo has filtered public configs, there can be an
action to copy these public configs to a public repo.

Each action is a function that takes a list of config repos to operate on and
returns a list of repos to make commits to.
"""

import os

from collections import namedtuple
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'cros_source',
    'gerrit',
    'git',
    'git_txn',
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
    with api.step.nest(project_info.name):
      public_config_path = api.context.cwd.join(project_info.path,
                                                'public_sw_build_config')
      api.path.mock_add_paths(public_config_path)
      if api.path.exists(public_config_path):
        # Parse the program and project name out of the project repo path. It is
        # expected that the project repo path has a format like
        # "src/project/<program>/<project>".
        #
        # The program and project names are then used to form the destination
        # path in the public repo.
        dirname, project_name = api.path.split(project_info.path)
        _, program_name = api.path.split(dirname)
        dest_path = public_repo_path.join(program_name, project_name,
                                          'sw_build_config')

        # file.copytree will fail if the destination exists. Thus, remove
        # dest_path before doing the copy.
        api.file.rmtree('remove dest dir', dest_path)
        api.file.copytree('copy public config', public_config_path, dest_path)

  return [CommitInfo(public_repo_path, 'Update with filtered configs.')]


def _flatten_configs(api, project_infos):
  flatten_script = api.context.cwd.join(
      'src/config/payload_utils/flatten_config_payload.py')

  joined_config = 'generated/joined.jsonproto'
  config_bundle = 'generated/config.jsonproto'
  flat_config = 'generated/flattened.jsonproto'

  def _flatten_config():
    with api.step.nest('find input config') as presentation:
      # figure out which input to use
      input_config = joined_config
      if not api.path.exists(api.context.cwd.join(input_config)):
        input_config = config_bundle
      presentation.step_text = input_config

      full_input = api.context.cwd.join(input_config)
      if not api.path.exists(full_input):
        presentation.step_summary_text = "(does not exist)"
        return False  # abort transaction

    # have input selected and we know it exists
    cmd = [
        flatten_script,
        "--input",
        input_config,
        "--output",
        flat_config,
    ]

    api.step('generate flat payload', ['vpython'] + cmd)
    api.git.add([flat_config])

    with api.step.nest("diffing to find changes"):
      changed_files = api.git.get_diff_files('HEAD')
      if not changed_files:
        return False  # abort transaction

    # commit files
    message = \
      '''Autogenerating flattened config payloads.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), 'config_postsubmit/flatten')
    api.git.commit(message)

  for project_info in project_infos:
    with api.step.nest('processing %s' % project_info.name) as presentation,\
         api.context(api.context.cwd.join(project_info.path)):
      try:
        api.git_txn.update_ref(
            project_info.remote,
            project_info.branch,
            _flatten_config,
        )
      except api.step.StepFailure:
        presentation.status = 'WARNING'

  return []


# A list of functions to run on config repos. Each action should take a
# RecipesApi and list of ProjectInfos as args and return a list of CommitInfos.
_ACTIONS = [
    _replicate_public_config,
    _flatten_configs,
]


def _get_config_projects(api):
  """Returns a list of ProjectInfos for all config repos."""
  return api.repo.project_infos(
      regexes=['chromeos/program', 'chromeos/project'])


def _create_cl(api, commit_info, branch_name):
  """Creates a CL based on commit_info.

  Args:
    api (RecipeApi): See RunSteps documentation.
    commit_info (CommitInfo): A CommitInfo object describing how to create the
      commit.
    branch_name (str): Name of the branch to create the commit on.
  """
  with api.context(cwd=commit_info.project_path):
    if api.git.diff_check(commit_info.project_path):
      api.repo.start(branch_name, projects=[commit_info.project_path])
      api.git.add([commit_info.project_path])
      api.git.commit(commit_info.message)

      # TODO(crbug.com/1092530): Add reviewers and / or automatically
      # submit changes once this is tested.
      api.gerrit.create_change(project=commit_info.project_path)


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(), \
    api.context(cwd=api.cros_source.workspace_path):

    api.cros_source.ensure_synced_cache()

    with api.step.nest('find config repos'):
      config_projects = _get_config_projects(api)

    # One action failing should not block all later actions from running. Thus,
    # catch StepFailures from each action and raise them later.
    #
    # Note that an action failing should stop the CL from being created (i.e. a
    # failed action might create an invalid CL), and thus api.step.defer_results
    # cannot be used.
    step_failures = []
    for action in _ACTIONS:
      # Use the name of the fn. to create step names, branch names, etc.
      action_name = action.__name__.strip('_')
      with api.step.nest('Do {} and create CL'.format(action_name)):
        try:
          commit_infos = action(api, config_projects)
          for commit_info in commit_infos:
            _create_cl(api, commit_info, action_name)
        except api.step.StepFailure as e:
          step_failures.append(e)

    # If there were any step failures, raise now.
    if step_failures:
      msg = '{} steps failed:'.format(len(step_failures))
      msg += ', '.join((f.reason or f.name) for f in step_failures)
      raise api.step.StepFailure(msg)


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
      api.git.diff_check(True),
      api.post_process(
          post_process.StepCommandContains,
          'Do replicate_public_config and create CL.chromeos/project/galaxy/milkyway.copy public config',
          [
              'copytree',
              '[START_DIR]/chromiumos_workspace/src/project/galaxy/milkyway/public_sw_build_config',
              '[START_DIR]/chromiumos_workspace/src/project_public/galaxy/milkyway/sw_build_config',
          ],
      ),
  )

  yield api.test(
      'failed_actions',
      config_repos_step_data(api),
      api.step_data(
          'Do replicate_public_config and create CL.chromeos/project/galaxy/milkyway.copy public config',
          retcode=1),
      api.post_process(post_process.DoesNotRunRE, 'git commit'),
      api.post_process(post_process.StatusFailure),
      api.post_process(
          post_process.ResultReason,
          "1 steps failed:Infra Failure: Step('Do replicate_public_config and create CL.chromeos/project/galaxy/milkyway.copy public config') (retcode: 1)"
      ),
      api.post_process(post_process.DropExpectation),
  )

  # flattening stage tests
  def StepSummaryEquals(check, step_odict, step, expected):
    """Check that the step's step_summary_text equals given value.

    Args:
      step (str) - The step to check the step_text of
      expected (str) - The expected value of the step_text

    Usage:
      yield TEST + api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_summary_text == expected)

  def mock_payloads(fname):
    return api.path.exists(api.path['start_dir'].join(
        'chromiumos_workspace/src/project/galaxy/milkyway/generated/%s' %
        fname))

  yield api.test(
      'flattening_basic',
      config_repos_step_data(api),
      mock_payloads("config.jsonproto"),
      api.git.diff_check(True),
      api.post_process(
          post_process.MustRun,
          'Do flatten_configs and create CL.processing chromeos/project/galaxy/milkyway.git transaction.git push'
      ),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL.processing chromeos/program/galaxy.git transaction.git push'
      ),
  )

  yield api.test(
      'no_flattening_changes',
      config_repos_step_data(api),
      mock_payloads("config.jsonproto"),
      api.git.diff_check(True),
      api.step_data(
          'Do flatten_configs and create CL.processing chromeos/project/galaxy/milkyway.git transaction.diffing to find changes.git diff',
          stdout=api.raw_io.output('')),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL.processing chromeos/project/galaxy/milkyway.git transaction.git push'
      ),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL.processing chromeos/program/galaxy.git transaction.git push'
      ),
  )

  yield api.test(
      'flattening_error',
      config_repos_step_data(api),
      mock_payloads("config.jsonproto"),
      api.step_data(
          'Do flatten_configs and create CL.processing chromeos/project/galaxy/milkyway.git transaction.generate flat payload',
          retcode=1),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL.processing chromeos/project/galaxy/milkyway.git transaction.git push'
      ),
  )

  yield api.test(
      'no_input_files',
      config_repos_step_data(api),
      api.post_process(
          StepSummaryEquals,
          'Do flatten_configs and create CL.processing chromeos/project/galaxy/milkyway.git transaction.find input config',
          "(does not exist)"),
  )
