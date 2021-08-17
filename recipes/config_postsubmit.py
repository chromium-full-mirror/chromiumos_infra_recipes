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

from collections import namedtuple
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'git_txn',
    'repo',
    'src_state',
    'workspace_util',
]

from PB.recipes.chromeos.config_postsubmit import ConfigPostsubmitProperties

PROPERTIES = ConfigPostsubmitProperties

# Represents a commit that should be made as the result of an action.
#
# Fields:
#  project_path (str): Path to the repo to commit to.
#  message (str): Commit message.
#  files (list[paths]): Files to add to commit, if empty will add project_path.
CommitInfo = namedtuple('CommitInfo', ['project_path', 'message', 'files'])

# Represents the config for a data ingestion/aggregation task.
#
# Fields:
#   name (str): name of the task for display purposes
#   input_path (str): input path in each project
#   output_path (str): output path in config-internal
#   message_type (str): message type to read in from projects
#   aggregate_type (str): aggregate message type to write to config-internal
#
IngestConfig = namedtuple(
    'IngestConfig',
    ['name', 'input_path', 'output_path', 'message_type', 'aggregate_type'],
)


def _replicate_public_config(api, _properties, project_infos):
  """Replicates any public configs in project repos into a public repo.

  Args:
    See notes on _ACTIONS.
  """
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


def _flatten_configs(api, properties, project_infos):
  flatten_script = api.context.cwd.join(
      'src/config/payload_utils/flatten_config_payload.py')

  allowed_projects = [
      project.repo_name for project in properties.allowed_projects
  ]

  allowed_programs = [
      program.repo_name for program in properties.allowed_programs
  ]

  cwd = api.context.cwd
  merge_script = cwd.join('src/config/payload_utils/aggregate_messages.py')
  program_join_script = cwd.join('src/config/payload_utils/join_programs.py')

  joined_config = 'generated/joined.jsonproto'
  config_bundle = 'generated/config.jsonproto'
  flat_config = 'generated/flattened.jsonproto'
  binary_flat_config = 'generated/flattened.binaryproto'

  # Get paths of all generated program payloads
  files = []
  for project_info in project_infos:
    if not project_info.name in allowed_programs:
      continue

    path = cwd.join(project_info.path, 'generated/config.jsonproto')
    if api.path.exists(path):
      files.append(path)

  program_configs_path = api.path.mkstemp()
  # yapf: disable
  api.step('aggregating program configs', [
    'vpython', merge_script,
    '-m', 'chromiumos.config.payload.ConfigBundle',
    '-a', 'chromiumos.config.payload.ConfigBundleList',
    '-o', program_configs_path] + files)
  # yapf:enable

  flat_files = []

  # generated a temporary flattened.jsonproto in each project
  empty_flatten_payload = []
  for project_info in project_infos:
    if not project_info.name.startswith("chromeos/project"):
      continue

    with api.step.nest('processing %s' % project_info.name) as presentation,\
         api.context(api.context.cwd.join(project_info.path)):

      if not project_info.name in allowed_projects:
        presentation.step_summary_text = "skipping, not in allowed projects"
        continue

      # if no joined configuration (not backfilled), use the ConfigBundle
      input_config = joined_config
      if not api.path.exists(api.context.cwd.join(input_config)):
        input_config = config_bundle
      presentation.step_text = input_config

      full_input = api.context.cwd.join(input_config)
      if not api.path.exists(full_input):
        presentation.step_summary_text = "(does not exist)"
        continue

      # have input selected and we know it exists, generate a flattened file
      cmd = [
          flatten_script,
          "--input",
          input_config,
          "--output",
          flat_config,
      ]

      result = api.step(
          'generate flat payload',
          ['vpython'] + cmd,
          stdout=api.raw_io.output_text(),
      )

      # note if we had no flattened entries for project
      nflat = int(result.stdout.strip())
      if nflat == 0:
        program, project = project_info.name.split("/")[2:4]
        empty_flatten_payload.append([program, project])

      flat_files.append(api.context.cwd.join(flat_config))

  # store empty flattened payloads into the output properties
  api.easy.set_properties_step(empty_flatten_payload=empty_flatten_payload)

  # now merge and import into config-internal
  cwd = api.context.cwd
  merge_script = cwd.join('src/config/payload_utils/aggregate_messages.py')
  config_internal = cwd.join('src/config-internal')
  output_path = config_internal.join('hw_design', flat_config)
  binary_output_path = config_internal.join('hw_design', binary_flat_config)

  def _merge_flattened():
    project_configs_path = api.path.mkstemp()

    # Merge all the flattened projet configs together into a single payload
    # yapf: disable
    cmd = [
        merge_script,
        '-m', 'chromiumos.config.payload.FlatConfigList',
        '-a', 'chromiumos.config.payload.FlatConfigList',
        '-o', project_configs_path,
    ] + flat_files
    # yapf: enable

    api.step('merge flattened configs to config-internal', ['vpython'] + cmd)

    # join with program definitions
    # yapf: disable
    api.step('joining program and project configs', [
      'vpython', program_join_script,
      '-l', 'debug',
      '-o', output_path,
      '-b', binary_output_path,
      '-i', project_configs_path,
      '-p', program_configs_path
    ])
    # yapf: enable

    with api.step.nest("diffing to find changes") as presentation:
      if not api.git.diff_check(output_path):
        presentation.step_summary_text = "No changes to commit"
        return False  # abort transaction

    # commit files
    api.git.add([output_path, binary_output_path])

    automation_id = 'config_postsubmit/merge_flattened'
    message = \
      '''Automerging and importing flattened configs.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), automation_id)
    api.git.commit(message)
    return True

  # git transaction wrapper around _merge_flattened
  with api.context(config_internal),\
       api.step.nest("aggregating flattened configs") as presentation:

    config_project_info = api.repo.project_info("chromeos/config-internal")

    api.git_txn.update_ref(
        config_project_info.remote,
        _merge_flattened,
        ref=config_project_info.branch,
    )

    return []


def _aggregate_configs(api, properties, project_infos):
  """Aggregate config messages and copy them to multiple locations.

  1. config-internal - This provides a single centralized location from which
  services can read all device configurations.
  2. UFS datastore - This enables the usage of configs as schedulable labels.
  """
  configs = [
      IngestConfig(
          'joined',
          'generated/joined.jsonproto',
          'hw_design/generated/configs.jsonproto',
          'chromiumos.config.payload.ConfigBundle',
          'chromiumos.config.payload.ConfigBundleList',
      ),
  ]

  allowed_projects = [
      project.repo_name for project in properties.allowed_projects
  ]

  # get project info for internal config repo
  config_project_info = api.repo.project_info("chromeos/config-internal")

  cwd = api.context.cwd
  merge_script = cwd.join('src/config/payload_utils/aggregate_messages.py')
  config_internal = cwd.join('src/config-internal')

  def _merge_configs():
    outputs = []
    for config in configs:
      # find all the input config files
      files = []
      for project_info in project_infos:
        if not project_info.name in allowed_projects:
          continue

        path = cwd.join(project_info.path, config.input_path)

        if api.path.exists(path):
          files.append(path)

      # merge and import
      api.step('merge {} configs to config-internal'.format(config.name), [
          'vpython', merge_script, "-m", config.message_type, "-a",
          config.aggregate_type, "-o", config.output_path
      ] + files)

      outputs.append(config.output_path)

    with api.step.nest("diffing to find changes") as presentation:
      if not any(api.git.diff_check(output) for output in outputs):
        presentation.step_summary_text = "No changes to commit"
        return False  # abort transaction

    # commit files
    api.git.add(outputs)
    automation_id = 'config_postsubmit/aggregate'
    message = \
      '''Automerging and importing config changes.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(), automation_id)
    api.git.commit(message)
    return True

  with api.context(config_internal),\
       api.step.nest("aggregating configs"):

    api.git_txn.update_ref(config_project_info.remote, _merge_configs,
                           ref=config_project_info.branch)

  config_to_ufs_datastore = cwd.join(
      'src/config/payload_utils/config_to_datastore.py')
  ufs_env = "prod"

  # only need to upload for not flattened configs; need to determine condition
  with api.context(config_internal),\
       api.step.nest("upload configs to ufs"):

    api.step("upload generated configs to UFS datastore", [
        "vpython",
        config_to_ufs_datastore,
        "--env",
        ufs_env,
    ])

  return []


def _regenerate_suite_scheduler_configs(api, _properties, _project_infos):
  """Run Suite Scheduler configuration's ./generate and commit the results.

  This action runs the generate function in src/config-internal/test and commits
  the results.

  Args:
    project_infos: ignored, but accepted. See notes on _ACTIONS.
  """
  config_internal = api.context.cwd.join('src/config-internal')
  cfg_int_ss = config_internal.join('test/suite_scheduler')

  regenerated_files = [
      cfg_int_ss.join('generated/suite_scheduler.cfg'),
      cfg_int_ss.join('generated/lab_config.cfg'),
      cfg_int_ss.join('generated/lab_config.ini'),
      cfg_int_ss.join('generated/suite_scheduler.ini'),
  ]

  message = '''Updating Suite Scheduler's generated rules.

Cr-Build-Url: %s
Cr-Automation-Id: %s''' % (api.buildbucket.build_url(),
                           'config_postsubmit/regenerate_suite_scheduler')

  with api.step.nest('regenerating suite scheduler configs') as presentation, \
      api.context(cfg_int_ss):

    api.step('run regenerate_configs.sh', ['./regenerate_configs.sh'])

    with api.step.nest('diffing to find changes'):
      nothing_changed = not any(
          api.git.diff_check(x) for x in regenerated_files)
      if nothing_changed:
        presentation.step_text = 'no changes'
        return []

    return [CommitInfo(config_internal, message, regenerated_files)]


def _regenerate_test_plan(api, _properties, _project_infos):
  """Run test configurations ./generate and ./generate_test_plan_summary.

  This action runs the generate function in src/config-internal/test and commits
  the results.

  Args:
    project_infos: ignored, but accepted. See notes on _ACTIONS.
  """
  config_internal = api.context.cwd.join("src/config-internal")
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
# optionally return a list of CommitInfos.
_ACTIONS = {
    PROPERTIES.REPLICATE_PUBLIC_CONFIG: _replicate_public_config,
    PROPERTIES.FLATTEN_CONFIGS: _flatten_configs,
    PROPERTIES.COPY_TO_INTERNAL: _aggregate_configs,
    PROPERTIES.REGENERATE_SUITE_SCHEDULER: _regenerate_suite_scheduler_configs,
    PROPERTIES.REGENERATE_TEST_PLAN: _regenerate_test_plan,
}


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
              api.gerrit.Label.BOT_COMMIT: 1,
              api.gerrit.Label.COMMIT_QUEUE: 2,
          })


def RunSteps(api, properties):

  def _get_config_projects():
    """Returns a list of ProjectInfos for all config repos."""

    # load all the repos defined in the DLM config.
    all_program_configs = api.file.read_json(
        "reading DLM config",
        api.context.cwd.join(
            "infra/config/project_config/all_programs_config.json"))

    names = set()
    for program in all_program_configs.get("programs", []):
      name = program.get("repo", {}).get("name")
      if name:
        names.add(name)

      for project in program.get("deviceProjects", []):
        name = project.get("repo", {}).get("name")
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
            commit_infos = action(api, properties, config_projects)
            for commit_info in commit_infos:
              _create_cl(api, properties, commit_info, action_name, cl_config)
          except StepFailure as e:
            step_failures.append(e)

      # format markdown
      markdown = ""
      if step_failures:
        lines = ["%d steps failed:\n" % len(step_failures)]
        for failure in step_failures:
          lines += ["- %s\n" % failure.reason or failure.name]

        # truncate markdown to 4K to avoid INFRA_FAILURE
        markdown = lines[0]
        for line in lines[1:]:
          if len(markdown) + len(line) < 3990:
            markdown += '\n\n' + line
          else:  #pragma: nocover
            markdown += '\n\n...'
            break

      # return RawResult directly to set the markdown (only with luciexe)
      return result_pb2.RawResult(
          status=common_pb2.FAILURE if step_failures else common_pb2.SUCCESS,
          summary_markdown=markdown)


def GenTests(api):

  def default_properties(allowed_projects=None, allowed_programs=None):
    if allowed_projects is None:
      allowed_projects = [{"repo_name": "chromeos/project/galaxy/milkyway"}]

    if allowed_programs is None:
      allowed_programs = [{"repo_name": "chromeos/program/galaxy"}]

    aclc = PROPERTIES.ActionCLConfig(
        reviewers='test1@google.com',
        ccs=['test2@google.com', 'test3@google.com'], topic='test topic',
        hashtags=['ht1', 'ht2'], send_to_cq=True)
    return api.properties(
        PROPERTIES(
            cl_configs={
                "REGENERATE_SUITE_SCHEDULER": aclc,
                "FLATTEN_CONFIGS": aclc,
                "COPY_TO_INTERNAL": aclc,
                "REPLICATE_PUBLIC_CONFIG": aclc,
                "REGENERATE_TEST_PLAN": aclc,
            },
            allowed_programs=allowed_programs,
            allowed_projects=allowed_projects,
        ))

  def config_dlm_step_data(api):
    return api.step_data(
        'find config repos.reading DLM config',
        api.file.read_json({
            "programs": [{
                "repo": {
                    "name": "chromeos/program/galaxy",
                },
                "deviceProjects": [{
                    "repo": {
                        "name": "chromeos/project/galaxy/milkyway"
                    }
                },]
            }]
        }),
    )

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
      api.post_process(post_process.StatusFailure),
      api.post_process(
          post_process.ResultReason,
          "1 steps failed:\n\n\n- Infra Failure: "              \
               "Step('Do replicate_public_config and create CL" \
                   ".chromeos/project/galaxy/milkyway"          \
                   ".copy public config') (retcode: 1)\n"
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
      yield TEST + \
          api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_summary_text == expected)

  def mock_project_payloads(fname):
    return api.path.exists(
        api.src_state.workspace_path.join(
            'src/project/galaxy/milkyway/generated/%s' % fname))

  def mock_program_payloads():
    return api.path.exists(
        api.src_state.workspace_path.join(
            'src/program/galaxy/generated/config.jsonproto'))

  def flatten_step_data(value):
    """Returns StepData for the call to flatten_config_payload.py call."""
    data = api.step_data(
        'Do flatten_configs and create CL'               \
          '.processing chromeos/project/galaxy/milkyway' \
          '.generate flat payload',
        stdout=api.raw_io.output_text(str(value) + '\n'),
    )
    return data

  yield api.test(
      'flattening_basic',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      api.git.diff_check(True),
      flatten_step_data(1),
      api.post_process(
          post_process.MustRun,
          'Do flatten_configs and create CL'                 \
              '.processing chromeos/project/galaxy/milkyway' \
              '.generate flat payload'
      ),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL'        \
              '.processing chromeos/program/galaxy' \
              '.generate flat payload'
      ),
  )

  yield api.test(
      'flattening_not_allowed_project',
      default_properties(allowed_projects=[]),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      api.git.diff_check(True),
      api.post_process(
          StepSummaryEquals,
          'Do flatten_configs and create CL' \
              '.processing chromeos/project/galaxy/milkyway',
          'skipping, not in allowed projects'),
  )

  yield api.test(
      'flattening_no_entries',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      api.git.diff_check(True),
      flatten_step_data(0),
      api.post_process(
          post_process.PropertyEquals,
          "empty_flatten_payload",
          [["galaxy", "milkyway"]],
      ),
  )

  yield api.test(
      'no_flattening_changes',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      mock_project_payloads("joined.jsonproto"),
      api.git.diff_check(False),
      flatten_step_data(1),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL'   \
              '.aggregating flattened configs' \
              '.update ref.git transaction.git push'
      ),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL'   \
              '.aggregating flattened configs' \
              '.update ref.git transaction.git push'
      ),
  )

  yield api.test(
      'flattening_error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      flatten_step_data(1),
      api.step_data(
          'Do flatten_configs and create CL'
          '.aggregating flattened configs'
          '.update ref.git transaction.'
          'merge flattened configs to config-internal', retcode=1),
      api.post_process(
          post_process.DoesNotRun,
          'Do flatten_configs and create CL'
          '.aggregating flattened configs'
          '.update ref.git transaction.git push',
      ),
  )

  yield api.test(
      'no_input_files',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      api.post_process(
          StepSummaryEquals,
          'Do flatten_configs and create CL' \
              '.processing chromeos/project/galaxy/milkyway',
          "(does not exist)"),
  )

  # import to internal config stage tests
  yield api.test(
      'aggregate_configs_basic',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      mock_project_payloads("flattened.jsonproto"),
      mock_program_payloads(),
      api.git.diff_check(True),
      api.post_process(
          post_process.MustRun,
          'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.merge joined configs'
          ' to config-internal',
      ),
      api.post_process(
          post_process.MustRun,
          'Do aggregate_configs and create CL'
          '.upload configs to ufs'
          '.upload generated configs to UFS datastore',
      ),
      api.post_process(
          post_process.DoesNotRun,
          'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.merge flattened configs'
          ' to config-internal',
      ),
  )

  yield api.test(
      'aggregate_configs_no_diff',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_program_payloads(),
      mock_project_payloads("config.jsonproto"),
      mock_project_payloads("flattened.jsonproto"),
      api.git.diff_check(False),
      api.post_process(
          StepSummaryEquals, 'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.diffing to find changes',
          "No changes to commit"),
      api.post_process(
          post_process.MustRun,
          'Do aggregate_configs and create CL'
          '.upload configs to ufs'
          '.upload generated configs to UFS datastore',
      ),
  )

  yield api.test(
      'aggregate_configs_error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_program_payloads(),
      mock_project_payloads("config.jsonproto"),
      mock_project_payloads("flattened.jsonproto"),
      api.git.diff_check(True),
      api.step_data(
          'Do aggregate_configs and create CL'
          '.aggregating configs'
          '.update ref.git transaction.merge '
          'joined configs to config-internal', retcode=1),
  )

  yield api.test(
      'regenerate_suite_scheduler_configs_error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      mock_project_payloads("flattened.jsonproto"),
      api.git.diff_check(True),
      api.step_data(
          'Do regenerate_suite_scheduler_configs and create CL' \
              '.regenerating suite scheduler configs'           \
              '.run regenerate_configs.sh',
          retcode=1),
      api.post_process(
          post_process.DoesNotRun,
          'Do regenerate_suite_scheduler_configs and create CL' \
              '.regenerating suite scheduler configs'           \
              '.diffing to find changes',
      ),
  )

  yield api.test(
      'regenerate_test_plan_error',
      default_properties(),
      config_repos_step_data(api),
      config_dlm_step_data(api),
      mock_project_payloads("config.jsonproto"),
      mock_project_payloads("flattened.jsonproto"),
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
  )
