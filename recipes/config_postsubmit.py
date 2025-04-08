# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
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

from collections import OrderedDict
from collections import namedtuple

from RECIPE_MODULES.chromeos.gerrit.api import Label

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.config_postsubmit import ConfigPostsubmitProperties
from recipe_engine import post_process
from recipe_engine import recipe_api

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_scaling',
    'cros_source',
    'easy',
    'failures',
    'future_utils',
    'gerrit',
    'git',
    'git_txn',
    'repo',
    'src_state',
    'workspace_util',
]


PROPERTIES = ConfigPostsubmitProperties

# Represents a commit that should be made as the result of an action.
#
# Fields:
#  project_path (str): Path to the repo to commit to.
#  message (str): Commit message.
CommitInfo = namedtuple('CommitInfo', ['project_path', 'message'])


def _replicate_public_config(api, _properties, project_infos, dry_run):
  """Replicates any public configs in project repos into a public repo.

  Args:
    See notes on _ACTIONS.
  """
  del dry_run
  public_repo_path = api.context.cwd / 'src' / 'project_public'

  automation_id = 'config_postsubmit/replicate_public'
  message = \
    '''Update with publically filtered configs.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), automation_id)

  for project_info in project_infos:
    with api.step.nest(project_info.name):
      public_config_path = (
          api.context.cwd / project_info.path / 'public_sw_build_config')
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
        dest_path = public_repo_path.joinpath(program_name, project_name,
                                              'sw_build_config')

        # file.copytree will fail if the destination exists. Thus, remove
        # dest_path before doing the copy.
        api.file.rmtree('remove dest dir', dest_path)
        api.file.copytree('copy public config', public_config_path, dest_path)

  return [CommitInfo(public_repo_path, message)]


def _update_device_stability(api, properties, _project_infos, dry_run):
  """Update the device stability configs in UFS.

  Uses the config_to_datastore script to do the update.

  Args:
    project_infos: ignored, but accepted. See notes on _ACTIONS.
  """
  del dry_run  # Unused.

  cwd = api.context.cwd
  config_internal = cwd / 'src/config-internal'

  config_to_ufs_datastore = (
      cwd / 'src/config/payload_utils/config_to_datastore.py')

  ufs_env = properties.ufs_env or 'prod'

  with api.context(config_internal),\
       api.step.nest('upload configs to ufs'):

    api.step('upload generated configs to UFS datastore', [
        config_to_ufs_datastore,
        '--debug',
        '--env',
        ufs_env,
    ])

  return []


# A map of CL configurations -> their functions which run on config repos.
#
# Each action should take a RecipesApi and list of ProjectInfos as args and
# optionally return a list of CommitInfos. In addition, each action should take
# a dry_run arg, to control interaction with external services, e.g. committing
# directly to git instead of returning a CommitInfo.
_ACTIONS = OrderedDict([
    (PROPERTIES.REPLICATE_PUBLIC_CONFIG, _replicate_public_config),
    (PROPERTIES.COPY_TO_INTERNAL, _update_device_stability),
])


def _create_cl(
    api: recipe_api.RecipeApi,
    _properties: ConfigPostsubmitProperties,
    commit_info: CommitInfo,
    branch_name: str,
    cl_config: ConfigPostsubmitProperties.ActionCLConfig,
) -> common_pb2.GerritChange:
  """Creates a CL based on commit_info.

  Args:
    api: See RunSteps documentation.
    commit_info: A CommitInfo object describing how to create the
      commit.
    branch_name: Name of the branch to create the commit on.
    cl_config: CL parameters & configuration.

    Returns:
      The newly created change.
  """
  with api.context(cwd=commit_info.project_path):
    if api.git.get_working_dir_diff_files():
      api.repo.start(branch_name, projects=[commit_info.project_path])

      api.git.add([commit_info.project_path])
      api.git.commit(commit_info.message)
      change = api.gerrit.create_change(project=commit_info.project_path,
                                        reviewers=cl_config.reviewers,
                                        ccs=cl_config.ccs,
                                        hashtags=cl_config.hashtags,
                                        topic=cl_config.topic)
      if cl_config.send_to_cq:
        with api.step.nest('send to CQ'):
          api.gerrit.set_change_labels(change, {
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          })
      if cl_config.abandon:
        api.gerrit.abandon_change(change)


def RunSteps(api, properties):

  def _get_config_projects():
    """Returns a list of ProjectInfos for all config repos."""

    # load all the repos defined in the DLM config.
    all_program_configs = api.file.read_json(
        'reading DLM config', api.context.cwd /
        'infra/config/project_config/all_programs_config.json')

    names = set()
    for program in all_program_configs.get('programs', []):
      name = program.get('repo', {}).get('name')
      if name:
        names.add(name)

      for project in program.get('deviceProjects', []):
        name = project.get('repo', {}).get('name')
        if name:
          names.add(name)

    project_infos = api.repo.project_infos(
        regexes=['chromeos/program', 'chromeos/project'])

    # filter out any projects not defined in DLM to avoid problems with
    # cancelled/removed projects who's repos haven't been deleted yet.
    return [info for info in project_infos if info.name in names]

  with api.workspace_util.setup_workspace(default_main=True):
    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()

    with api.context(cwd=api.cros_source.workspace_path):

      with api.step.nest('find config repos'):
        config_projects = _get_config_projects()

      # One action failing should not block all later actions from
      # running. Thus, catch StepFailures from each action and raise them later.
      #
      # Note that an action failing should stop the CL from being created
      # (i.e. a failed action might create an invalid CL), and thus
      # api.step.defer_results cannot be used.

      step_failures = []
      for cl_config_type, action in _ACTIONS.items():
        cl_config = properties.cl_configs[PROPERTIES.ActionTypes.Name(
            cl_config_type)]
        # Use the name of the fn. to create step names, branch names, etc.
        action_name = action.__name__.strip('_')
        with api.step.nest('Do {} and create CL'.format(action_name)):
          try:
            commit_infos = action(api, properties, config_projects,
                                  dry_run=not cl_config.send_to_cq)
            for commit_info in commit_infos:
              _create_cl(api, properties, commit_info, action_name, cl_config)
          except recipe_api.StepFailure as e:
            step_failures.append(e)

      # return RawResult directly to set the markdown (only with luciexe)
      return result_pb2.RawResult(
          status=common_pb2.FAILURE if step_failures else common_pb2.SUCCESS,
          summary_markdown=api.failures.format_step_failures(
              step_failures=step_failures))


def GenTests(api):

  def default_properties(allowed_projects=None, allowed_programs=None,
                         abandon: bool = False):
    if allowed_projects is None:
      allowed_projects = [{'repo_name': 'chromeos/project/galaxy/milkyway'}]

    if allowed_programs is None:
      allowed_programs = [{'repo_name': 'chromeos/program/galaxy'}]

    aclc = PROPERTIES.ActionCLConfig(
        reviewers=['test1@google.com'],
        ccs=['test2@google.com', 'test3@google.com'], topic='test topic',
        hashtags=['ht1', 'ht2'], send_to_cq=True, abandon=abandon)
    return api.properties(
        PROPERTIES(
            cl_configs={
                'REGENERATE_SUITE_SCHEDULER': aclc,
                'FLATTEN_CONFIGS': aclc,
                'COPY_TO_INTERNAL': aclc,
                'REPLICATE_PUBLIC_CONFIG': aclc,
                'REGENERATE_TEST_PLAN': aclc,
            },
            allowed_programs=allowed_programs,
            allowed_projects=allowed_projects,
        ))

  def config_dlm_step_data(api):
    return api.step_data(
        'find config repos.reading DLM config',
        api.file.read_json({
            'programs': [
                {
                    'repo': {
                        'name': 'chromeos/program/galaxy',
                    },
                    'deviceProjects': [{
                        'repo': {
                            'name': 'chromeos/project/galaxy/milkyway'
                        }
                    },]
                },
                {
                    'repo': {
                        'name': 'chromeos/program/otherprogram',
                    },
                },
            ]
        }),
    )

  def config_repos_step_data(api):
    """Returns StepData for the find config repos call."""
    return api.step_data(
        'find config repos.repo forall', stdout=api.raw_io.output_text(
            '\n'.join(
                '{}|{}|cros|refs/heads/main|refs/heads/main'.format(name, path)
                for name, path in [
                    ('chromeos/project/galaxy/milkyway',
                     'src/project/galaxy/milkyway'),
                    ('chromeos/program/galaxy', 'src/program/galaxy'),
                    ('chromeos/program/otherprogram',
                     'src/program/otherprogram'),
                ]),
        ))

  yield api.test(
      'basic',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      api.git.diff_check(True),
      api.post_process(
          post_process.StepCommandContains,
          'Do replicate_public_config and create CL' \
              '.chromeos/project/galaxy/milkyway'    \
              '.copy public config',
          [
              'copytree',
              '[CLEANUP]/chromiumos_workspace/src/' \
                  'project/galaxy/milkyway/public_sw_build_config',
              '[CLEANUP]/chromiumos_workspace/src/' \
                  'project_public/galaxy/milkyway/sw_build_config',
          ],
      ),
      api.post_check(post_process.DoesNotRunRE, r'.*\.abandon CL.*'),
  )

  yield api.test(
      'failed_actions',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      api.step_data(
          'Do replicate_public_config and create CL' \
              '.chromeos/project/galaxy/milkyway'    \
              '.copy public config',
          retcode=1),
      api.post_process(post_process.DoesNotRunRE, 'git commit'),
      api.post_process(
          post_process.SummaryMarkdown,
          '1 step failed:\n\n\n- Infra Failure: '              \
               "Step('Do replicate_public_config and create CL" \
                   '.chromeos/project/galaxy/milkyway'          \
                   ".copy public config') (retcode: 1)\n"
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'abandon-cl', default_properties(abandon=True),
      config_repos_step_data(api), config_dlm_step_data(api),
      api.post_check(post_process.MustRunRE,
                     r'Do \w* and create CL.abandon CL 1'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'update_device_stability-basic',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      api.post_process(
          post_process.MustRun,
          'Do update_device_stability and create CL'
          '.upload configs to ufs'
          '.upload generated configs to UFS datastore',
      ),
  )
