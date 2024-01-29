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
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_source',
    'easy',
    'failures',
    'gerrit',
    'git',
    'git_txn',
    'repo',
    'src_state',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ConfigPostsubmitProperties

# Represents a commit that should be made as the result of an action.
#
# Fields:
#  project_path (str): Path to the repo to commit to.
#  message (str): Commit message.
#  files (list[paths]): Files to add to commit, if empty will add project_path.
CommitInfo = namedtuple('CommitInfo', ['project_path', 'message', 'files'])


def _replicate_public_config(api, _properties, project_infos, dry_run):
  """Replicates any public configs in project repos into a public repo.

  Args:
    See notes on _ACTIONS.
  """
  del dry_run
  public_repo_path = api.context.cwd.join('src', 'project_public')

  automation_id = 'config_postsubmit/replicate_public'
  message = \
    '''Update with publically filtered configs.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), automation_id)

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

  return [CommitInfo(public_repo_path, message, [])]


def _aggregate_configs(api, properties, repo_project_infos, dry_run):
  """Aggregate ConfigBundle messages and copy them to multiple locations.

  1. config-internal - This provides a single centralized location from which
  services can read all device configurations.
  2. UFS datastore - This enables the usage of configs as schedulable labels.
  """
  allowed_projects = [
      project.repo_name for project in properties.allowed_projects
  ]

  allowed_programs = [
      program.repo_name for program in properties.allowed_programs
  ]

  # get project info for internal config repo
  config_project_info = api.repo.project_info('chromeos/config-internal')

  cwd = api.context.cwd
  merge_script = cwd.join('src/config/payload_utils/aggregate_messages.py')
  vpython_spec = cwd.join('src/config/.vpython')
  config_internal = cwd.join('src/config-internal')

  def _merge_configs():
    # find all the input config files
    files = []
    for repo_project_info in repo_project_infos:
      # repo_project_info is a ProjectInfo object (defined in repo/api.py),
      # which describes a Gerrit project. allowed_projects and allowed_programs
      # contain the names of Gerrit repos associated with CrOS projects or
      # programs which contain ConfigBundles that should be merged, for example
      # 'chromeos/program/galaxy' or 'chromeos/project/galaxy/milkyway'. For
      # each ProjectInfo, check if its name is in the lists of allowed project
      # or program repos, and aggregate the ConfigBundle.
      #
      # Project ConfigBundles are under 'generated/joined.jsonproto', program
      # ConfigBundles are under 'generated/config.jsonproto'.
      if repo_project_info.name in allowed_projects:
        path = cwd.join(repo_project_info.path, 'generated/joined.jsonproto')
      elif repo_project_info.name in allowed_programs:
        path = cwd.join(repo_project_info.path, 'generated/config.jsonproto')
      else:
        continue  #pragma: nocover

      if api.path.exists(path):
        files.append(path)

    # merge and import
    output_path = 'hw_design/generated/configs.jsonproto'
    api.step(
        'merge ConfigBundles to config-internal',
        [
            'vpython3', '-vpython-spec', vpython_spec, merge_script, '-m',
            'chromiumos.config.payload.ConfigBundle', '-a',
            'chromiumos.config.payload.ConfigBundleList', '-o', output_path
        ] + files,
    )

    with api.step.nest('diffing to find changes') as presentation:
      if not api.git.diff_check(output_path):
        presentation.step_summary_text = 'No changes to commit'
        return False  # abort transaction

    # commit files
    api.git.add([output_path])
    automation_id = 'config_postsubmit/aggregate'
    message = \
      '''Automerging and importing config changes.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), automation_id)
    api.git.commit(message)
    return True

  with api.context(config_internal),\
       api.step.nest('aggregating configs'):

    api.git_txn.update_ref(config_project_info.remote, _merge_configs,
                           ref=config_project_info.branch, dry_run=dry_run)

  config_to_ufs_datastore = cwd.join(
      'src/config/payload_utils/config_to_datastore.py')
  vpython_spec = cwd.join('src/config/.vpython')

  ufs_env = properties.ufs_env or 'prod'

  with api.context(config_internal),\
       api.step.nest('upload configs to ufs'):

    api.step('upload generated configs to UFS datastore', [
        'vpython3',
        '-vpython-spec',
        vpython_spec,
        config_to_ufs_datastore,
        '--env',
        ufs_env,
    ])

  return []


def _regenerate_suite_scheduler_configs(api, _properties, _project_infos,
                                        dry_run):
  """Run Suite Scheduler configuration's ./generate and commit the results.

  This action runs the generate function in src/config-internal/test and commits
  the results.

  Args:
    project_infos: ignored, but accepted. See notes on _ACTIONS.
  """
  del dry_run

  config_internal = api.context.cwd.join('src/config-internal')
  cfg_int_ss = config_internal.join('test/suite_scheduler')

  regenerated_files = [
      cfg_int_ss.join('generated/suite_scheduler.cfg'),
      cfg_int_ss.join('generated/lab_config.cfg'),
      cfg_int_ss.join('generated/lab_config.ini'),
      cfg_int_ss.join('generated/suite_scheduler.ini'),
      cfg_int_ss.join('generated/rule_schedule_categories.ini'),
  ]

  message = '''Updating Suite Scheduler's generated rules.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(),
                           'config_postsubmit/regenerate_suite_scheduler')

  with api.step.nest('regenerating suite scheduler configs') as presentation, \
      api.context(cfg_int_ss):

    api.step('run regenerate_configs.py', ['./regenerate_configs.py'])

    with api.step.nest('diffing to find changes'):
      nothing_changed = not any(
          api.git.diff_check(x) for x in regenerated_files)
      if nothing_changed:
        presentation.step_text = 'no changes'
        return []

    return [CommitInfo(config_internal, message, regenerated_files)]


def _regenerate_test_plan(api, _properties, _project_infos, dry_run):
  """Run test configurations ./generate and ./generate_test_plan_summary.

  This action runs the generate function in src/config-internal/test and commits
  the results.

  Args:
    project_infos: ignored, but accepted. See notes on _ACTIONS.
  """
  del dry_run

  config_internal = api.context.cwd.join('src/config-internal')
  config_internal_test = config_internal.join('test')
  config_internal_test_plans = config_internal_test.join('plans')

  message = '''Updating generated test plans.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(),
                           'config_postsubmit/regenerate_test_plan')

  with api.step.nest('regenerating test plans') as presentation, \
      api.context(config_internal_test):

    api.step('run generate', ['./generate'])
    with api.step.nest('diffing to find changes'):
      if not api.git.diff_check(config_internal_test_plans):
        presentation.step_text = 'no changes'
        return []

    return [CommitInfo(config_internal_test_plans, message, [])]


# A map of CL configurations -> their functions which run on config repos.
#
# Each action should take a RecipesApi and list of ProjectInfos as args and
# optionally return a list of CommitInfos. In addition, each action should take
# a dry_run arg, to control interaction with external services, e.g. committing
# directly to git instead of returning a CommitInfo.
#
# Note: Order here matters, currently:
#         Flatten_configs must be ran before _aggregate_configs.
_ACTIONS = OrderedDict([
    (PROPERTIES.REPLICATE_PUBLIC_CONFIG, _replicate_public_config),
    (PROPERTIES.COPY_TO_INTERNAL, _aggregate_configs),
    (PROPERTIES.REGENERATE_SUITE_SCHEDULER,
     _regenerate_suite_scheduler_configs),
    (PROPERTIES.REGENERATE_TEST_PLAN, _regenerate_test_plan),
])


def _create_cl(api, _properties, commit_info, branch_name, cl_config):
  """Creates a CL based on commit_info.

  Args:
    api (RecipeApi): See RunSteps documentation.
    commit_info (CommitInfo): A CommitInfo object describing how to create the
      commit.
    branch_name (str): Name of the branch to create the commit on.
    cl_config (ActionCLConfig_pb2): CL parameters & configuration.

    Returns:
      GerritChange: The newly created change.
  """
  with api.context(cwd=commit_info.project_path):
    if api.git.get_working_dir_diff_files():
      api.repo.start(branch_name, projects=[commit_info.project_path])

      # If given a list of files, use that to add, otherwise add the whole
      # project.
      if commit_info.files:
        api.git.add(commit_info.files)
      else:
        api.git.add([commit_info.project_path])
      api.git.commit(commit_info.message)
      change = api.gerrit.create_change(project=commit_info.project_path,
                                        reviewers=cl_config.reviewers,
                                        ccs=cl_config.ccs,
                                        hashtags=cl_config.hashtags,
                                        topic=cl_config.topic)
      if change and cl_config.send_to_cq:
        with api.step.nest('send to CQ'):
          api.gerrit.set_change_labels(change, {
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          })


def RunSteps(api, properties):

  def _get_config_projects():
    """Returns a list of ProjectInfos for all config repos."""

    # load all the repos defined in the DLM config.
    all_program_configs = api.file.read_json(
        'reading DLM config',
        api.context.cwd.join(
            'infra/config/project_config/all_programs_config.json'))

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
          except StepFailure as e:
            step_failures.append(e)

      # return RawResult directly to set the markdown (only with luciexe)
      return result_pb2.RawResult(
          status=common_pb2.FAILURE if step_failures else common_pb2.SUCCESS,
          summary_markdown=api.failures.format_step_failures(
              step_failures=step_failures))


def GenTests(api):

  def default_properties(allowed_projects=None, allowed_programs=None):
    if allowed_projects is None:
      allowed_projects = [{'repo_name': 'chromeos/project/galaxy/milkyway'}]

    if allowed_programs is None:
      allowed_programs = [{'repo_name': 'chromeos/program/galaxy'}]

    aclc = PROPERTIES.ActionCLConfig(
        reviewers=['test1@google.com'],
        ccs=['test2@google.com', 'test3@google.com'], topic='test topic',
        hashtags=['ht1', 'ht2'], send_to_cq=True)
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
          post_process.ResultReason,
          '1 step failed:\n\n\n- Infra Failure: '              \
               "Step('Do replicate_public_config and create CL" \
                   '.chromeos/project/galaxy/milkyway'          \
                   ".copy public config') (retcode: 1)\n"
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  def mock_project_payloads(fname):
    return api.path.exists(
        api.src_state.workspace_path.join(
            'src/project/galaxy/milkyway/generated/%s' % fname))

  def mock_program_payloads():
    return api.path.exists(
        api.src_state.workspace_path.join(
            'src/program/galaxy/generated/config.jsonproto'))

  # import to internal config stage tests
  yield api.test(
      'aggregate_configs-basic',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads('config.jsonproto'),
      mock_program_payloads(),
      api.git.diff_check(True),
      api.post_process(
          post_process.MustRun,
          'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.merge ConfigBundles'
          ' to config-internal',
      ),
      api.post_process(
          post_process.MustRun,
          'Do aggregate_configs and create CL'
          '.upload configs to ufs'
          '.upload generated configs to UFS datastore',
      ),
  )

  yield api.test(
      'aggregate_configs-no-diff',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_program_payloads(),
      mock_project_payloads('config.jsonproto'),
      api.git.diff_check(False),
      api.post_process(
          post_process.StepSummaryEquals, 'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.diffing to find changes',
          'No changes to commit'),
      api.post_process(
          post_process.MustRun,
          'Do aggregate_configs and create CL'
          '.upload configs to ufs'
          '.upload generated configs to UFS datastore',
      ),
  )

  yield api.test(
      'aggregate_configs-error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_program_payloads(),
      mock_project_payloads('config.jsonproto'),
      api.git.diff_check(True),
      api.step_data(
          'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.merge '
          'ConfigBundles to config-internal', retcode=1),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'regenerate_suite_scheduler_configs-error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads('config.jsonproto'),
      api.git.diff_check(True),
      api.step_data(
          'Do regenerate_suite_scheduler_configs and create CL' \
              '.regenerating suite scheduler configs'           \
              '.run regenerate_configs.py',
          retcode=1),
      api.post_process(
          post_process.DoesNotRun,
          'Do regenerate_suite_scheduler_configs and create CL' \
              '.regenerating suite scheduler configs'           \
              '.diffing to find changes',
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'regenerate_test_plan-error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads('config.jsonproto'),
      api.git.diff_check(True),
      api.step_data(
          'Do regenerate_test_plan and create CL' \
              '.regenerating test plans'          \
              '.run generate',
          retcode=1),
      api.post_process(
          post_process.DoesNotRun,
          'Do regenerate_test_plan and create CL' \
              '.regenerating test plans'          \
              '.diffing to find changes',
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
