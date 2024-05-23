# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Used to create sweeping changes by creating CLs in many repos.

This recipe is currently focused on the use case of running gen_config in
program and project repositories. Invocation is most easily handled via the
cl_factory script in the chromiumos/config repo's bin directory:

https://chromium.googlesource.com/chromiumos/config/+/HEAD/bin/cl_factory

That script is a wrapper around the `bb add` command which ends up executing
something that looks like this:

bb add \
  -cl https://chrome-internal-review.googlesource.com/c/chromeos/program/galaxy/+/3095418 \
  -p 'repo_regexes=["src/project/galaxy"]' \
  -p 'message_template=Hello world\n\nBUG=chromium:1092954\nTEST=None' \
  -p 'reviewers=["reviewer@google.com"]' \
  -p 'hashtags=["mondo-update"]' \
  -p 'replace_strings=[{"file_glob": "*.star", "before": "_CLAMSHELL", "after": "_CONVERTIBLE"}]' \
  chromeos/infra/ClFactory

For more details on the input properties, see cl_factory.proto.
"""

import re
from typing import Generator
from typing import List
from typing import Optional
from typing import Tuple

from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.cl_factory import ClFactoryProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

PROPERTIES = ClFactoryProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_cq_depends',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'repo',
    'src_state',
    'workspace_util',
]


_CHROMIOUS_CONFIG_PROJECT = 'chromiumos/config'
_CHANGE_ID_REGEX = re.compile(r'^Change-Id: ', re.MULTILINE)


def RunSteps(api: RecipeApi, properties: ClFactoryProperties) -> None:
  _validate_inputs(properties)
  # Note that gerrit_changes is allowed to be empty.
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  with api.workspace_util.setup_workspace(default_main=True):

    # We must sync the cache before we touch the workspace (which includes
    # calling api.repo methods).  Start by syncing just the projects in
    # gerrit_changes.
    # Specify a reference, to reduce network traffic when we sync additional
    # projects from properties.repo_regexes.
    sync_projects = [gc.project for gc in gerrit_changes]
    api.cros_source.ensure_synced_cache(
        cache_path_override=api.cros_source.workspace_path, init_opts={
            'reference': api.cros_source.cache_path,
            'verbose': True
        }, sync_opts={'verbose': True}, projects=sync_projects)
    api.cros_source.checkout_tip_of_tree()

    with api.context(cwd=api.cros_source.workspace_path):
      with api.step.nest('find gerrit change repos') as pres:
        gc_infos = []
        if gerrit_changes:
          gc_infos = api.repo.project_infos(
              [gc.project for gc in gerrit_changes])
        else:
          pres.step_text = 'no input gerrit changes'

      with api.step.nest('find regex matching CL repos'):
        cl_infos = api.repo.project_infos(regexes=list(properties.repo_regexes))
        if len(cl_infos) == 0:
          regexes = ', '.join(
              ['"{}"'.format(v) for v in properties.repo_regexes])
          raise ValueError(
              'No matching projects found, for regex: {}'.format(regexes))

      with api.step.nest('find additional repos to sync'):
        sync_projects = _determine_sync_projects(api, gc_infos, cl_infos,
                                                 properties)
        api.repo.sync(projects=sync_projects, current_branch=True, verbose=True)

      if properties.manifest_branch:
        api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                        properties.manifest_branch)

      with api.step.nest('cherry-pick gerrit changes') as pres:
        if gerrit_changes:
          api.cros_source.apply_gerrit_changes(gerrit_changes)
        else:
          pres.step_text = 'no input gerrit changes to apply'

      # Start development branches for each project.
      api.repo.start('cl-factory', projects=[info.name for info in cl_infos])

      with api.step.nest('generate project change lists') as pres:
        changes, diffs = _make_changes(api, cl_infos, gerrit_changes,
                                       properties)
        if changes and gerrit_changes and properties.set_source_depends:
          _set_source_cq_depends(api, changes, gc_infos, gerrit_changes)

      with api.step.nest('summarize results') as pres:
        if not changes:
          pres.step_text = 'no change lists generated'
        else:
          pres.logs['unified_diff'] = _make_unified_diff(changes, diffs)
          gerrit_commands = _make_gerrit_commands(api, properties.hashtags,
                                                  changes)
          if gerrit_commands:
            pres.logs['gerrit_commands'] = gerrit_commands


def _validate_inputs(properties: ClFactoryProperties) -> None:
  """Validates the inputs to this recipe.

  Validates that the inputs to this recipe. An exception is thrown if a problem
  is found.

  Args:
    properties (ClFactoryProperties): recipe input properties.
  """
  if not properties.repo_regexes:
    raise ValueError('Projects to operate on must be specified by the '
                     'repo_regexes property.')

  if not properties.message_template:
    raise ValueError('A message_template property must specify how to create '
                     'commit messages')


def _make_changes(
    api: RecipeApi, cl_infos: List[ProjectInfo],
    gerrit_changes: List[GerritChange],
    properties: ClFactoryProperties) -> Tuple[List[GerritChange], List[str]]:
  """Creates and returns the generated change lists and their diffs

  Args:
    api: See RunSteps documentation.
    cl_infos: List of infos for the projects CLs are being
      made in. Corresponds to that found via repo_regexes.
    gerrit_changes: gerrit change inputs to the recipe,
      if any.
    properties: Input properties to the recipe.

  Returns:
    a tuple of generated changes and the diffs for those changes
  """
  diffs = []
  changes = []
  for info in cl_infos:
    with api.step.nest('working on project {}'.format(info.name)) as pres, \
        api.context(cwd=api.cros_source.workspace_path / info.path):

      _replace_strings(api, properties)
      _gen_config(api)

      # Note that we don't use api.git.diff_check here because it doesn't
      # handle empty repos well. The ls-files will report an error condition.
      if api.git.get_working_dir_diff_files():
        pres.step_text = 'diff'
        cl, diff = _make_cl(api, info, properties, gerrit_changes)
        changes.append(cl)
        diffs.append(diff)
      else:
        pres.step_text = 'no diff'
  return changes, diffs


def _make_cl(api: RecipeApi, info: ProjectInfo, properties: ClFactoryProperties,
             gerrit_changes: List[GerritChange]) -> Tuple[GerritChange, str]:
  """Makes and returns a generated gerrit change and their diffs.

  Makes and returns a generated gerrit change, assumes cwd is the project path.

  Args:
    api: See RunSteps documentation.
    info: project info of project making a change list for.
    properties: recipe input properties.
    gerrit_changes: gerrit change inputs to the recipe, if any.

  Returns:
    a tuple of generated changes and the diff for those changes
  """
  project_path = api.context.cwd
  commit_message = _make_commit_message(api, info, gerrit_changes, properties)
  api.git.add([project_path])
  test_stdout = '- before text\n+ after text'
  diff = api.easy.stdout_step('grab a diff', ['git', 'diff', '--cached'],
                              test_stdout=test_stdout).decode('utf-8')
  api.git.commit(commit_message)
  cl = api.gerrit.create_change(
      project=project_path,
      reviewers=list(properties.reviewers),
      ccs=list(properties.ccs),
      hashtags=list(properties.hashtags),
  )
  return cl, diff


def _set_source_cq_depends(api: RecipeApi, changes: List[GerritChange],
                           gc_infos: List[ProjectInfo],
                           gerrit_changes: List[GerritChange]) -> None:
  """Sets Cq-Depend on the input gerrit changes.

  Args:
    api: See RunSteps documentation.
    changes: List of generated gerrit changes.
    gc_infos: List of infos for the input gerrit changes.
    gerrit_changes: gerrit change inputs to the recipe, if any.
  """
  cq_depend = api.cros_cq_depends.get_cq_depend(changes)
  replacement = cq_depend + '\nChange-Id: '

  with api.step.nest('applying Cq-Depend to input projects'):
    for info, change in zip(gc_infos, gerrit_changes):
      with api.step.nest('applying Cq-Depend to {}'
                         .format(info.name)), \
          api.context(cwd=api.cros_source.workspace_path / info.path):

        # For the change description commands to work we must be operating
        # on a tracking branch.
        api.step('create cl_factory branch', [
            'git', 'checkout', '-b', '__cl_factory', '--track', '{}/{}'.format(
                info.remote, info.branch_name)
        ])
        description = api.gerrit.get_change_description(change)
        description = re.sub(_CHANGE_ID_REGEX, replacement, description)
        api.gerrit.set_change_description(change, description)


def _determine_sync_projects(api: RecipeApi, gc_infos: List[ProjectInfo],
                             cl_infos: List[ProjectInfo],
                             properties: ClFactoryProperties) -> List[str]:
  """Determines projects needing to be synced and returns them.

  Args:
    api: See RunSteps documentation.
    gc_infos: List of infos for the input gerrit changes.
    cl_infos: List of infos for the projects CLs are being
      made in. Corresponds to that found via repo_regexes.
    properties: Input properties to the recipe.

  Returns:
    List of projects to sync, returning an empty list to sync all.
  """
  if properties.full_repo_sync:
    return []
  # For now since this only does gen_config we are assuming as such.
  # Thus make sure that all projects that could be involved in config generation
  # are up to date even when not specified by gerrit changes or repos to make
  # CLs in. This would include chromiumos/config and all program repos.
  projects = {i.name for i in gc_infos + cl_infos}
  projects.add(_CHROMIOUS_CONFIG_PROJECT)
  program_infos = api.repo.project_infos(regexes=['chromeos/program'])
  projects.update({i.name for i in program_infos})
  return sorted(list(projects))


def _replace_strings(api: RecipeApi, properties: ClFactoryProperties) -> None:
  """Executes string replacements with cwd repo.

  Args:
    api: See RunSteps documentation.
    properties: recipe input properties.
  """
  with api.step.nest('replace_strings'):
    for rs in properties.replace_strings:
      for filename in api.file.glob_paths('find replace string files',
                                          api.context.cwd, rs.file_glob,
                                          test_data=['file.txt', 'file.star']):
        filedata = api.file.read_raw('read {}'.format(filename), filename,
                                     test_data='hello world').decode('utf-8')
        filedata = filedata.replace(rs.before, rs.after)
        api.file.write_raw('write {}'.format(filename), filename, str(filedata))


def _gen_config(api: RecipeApi) -> None:
  """Executes gen_config within cwd device configuration repo.

  Executes gen_config within the cwd device configuration repo. If gen_config or
  config.star are not found in the usual locations this step will ignore this
  repo. This is handy because the chromeos/project/private repo, for example, is
  not a regular device configuration repo but the easy regex, "src/project",
  will of course hit it.

  Args:
    api: See RunSteps documentation.
  """
  gen_config_path = api.context.cwd / 'config' / 'bin' / 'gen_config'
  config_path = api.context.cwd / 'config.star'

  api.path.mock_add_paths(gen_config_path)
  api.path.mock_add_paths(config_path)

  with api.step.nest('gen_config') as pres:
    if (not api.path.exists(gen_config_path) or
        not api.path.exists(config_path)):  # pragma: nocover
      pres.step_text = 'gen_config files not found'
    else:
      api.step('run gen_config config.star', [gen_config_path, config_path])


def _make_commit_message(api: RecipeApi, info: ProjectInfo,
                         gerrit_changes: List[GerritChange],
                         properties: ClFactoryProperties) -> str:
  """Makes the commit message for a generated gerrit change.

  Args:
    api: See RunSteps documentation.
    info: project info of project making a commit message for.
    gerrit_changes: gerrit change inputs to the recipe, if any.
    properties: Input properties to the recipe.

  Returns:
    commit message.
  """
  replacements = {
      'project': info.name,
      'path': info.path,
      'remote': info.remote,
  }
  try:
    message = properties.message_template.format(**replacements)
  except KeyError:
    # Unrecognized key in template. Use the template without interpolation.
    message = properties.message_template
  message += '\n\nGenerated by ClFactory, see {} for job details.'.format(
      api.buildbucket.build_url())
  if gerrit_changes:
    message += '\n\n{}'.format(
        api.cros_cq_depends.get_cq_depend(gerrit_changes))
  return message


def _make_unified_diff(changes: List[GerritChange], diffs: List[str]) -> str:
  """Makes a unified, single string, concatenation of all the diffs.

  Combines the given diffs into a single string with a small header that shows
  what project each particular diff comes from. The intention is for the user
  to get an overall view of what has changed and thus may be able to make an
  overall approval decision without visiting each change in gerrit.

  Args:
    changes: List of generated gerrit changes.
    diffs: List of diffs for the generated gerrit changes.

  Returns:
    unified diff.
  """
  unified_diff = ''
  for cl, diff in zip(changes, diffs):
    unified_diff += cl.project + '\n'
    unified_diff += '=' * 80
    unified_diff += '\n' + diff + '\n\n'
  return unified_diff


_CR_TEMPLATE = 'gerrit label-cr `gerrit {} --raw search "{} status:open {}"` 2'
_V_TEMPLATE = 'gerrit label-v `gerrit {} --raw search "{} status:open {}"` 1'
_CQ_TEMPLATE = 'gerrit label-cq `gerrit {} --raw search "{} status:open {}"` 2'
_ABANDON_TEMPLATE = (
    'gerrit abandon `./gerrit {} --raw search "{} status:open {}"`')


def _make_gerrit_commands(api: RecipeApi, hashtags: List[str],
                          changes: List[GerritChange]) -> Optional[str]:
  """Returns a the gerrit commands to review, verify, commit the changes.

  Returns a string containing the gerrit command line commands that can be used
  to review, verify, and commit the changes.

  Args:
    api: See RunSteps documentation.
    hashtags: List of hashtags applied to generated gerrit changes.
    changes: List of generated gerrit changes.

  Returns:
    str of approval commands suitable for presenting to the user, or None
      if no commands could be determined.
  """
  service_account = api.buildbucket.swarming_task_service_account
  owner = service_account if service_account else ''
  owner_constraint = 'owner:{}'.format(owner)
  hashtag_constraints = ' '.join(['hashtag:{}'.format(t) for t in hashtags])
  reviews = []
  verifies = []
  commits = []
  abandons = []
  if _has_changes_on_host(changes, 'chromium-review.googlesource.com'):
    cl_format = ['', owner_constraint, hashtag_constraints]
    reviews.append(_CR_TEMPLATE.format(*cl_format))
    verifies.append(_V_TEMPLATE.format(*cl_format))
    commits.append(_CQ_TEMPLATE.format(*cl_format))
    abandons.append(_ABANDON_TEMPLATE.format(*cl_format))
  if _has_changes_on_host(
      changes, 'chrome-internal-review.googlesource.com'):  # pragma: nocover
    cl_format = ['-i', owner_constraint, hashtag_constraints]
    reviews.append(_CR_TEMPLATE.format(*cl_format))
    verifies.append(_V_TEMPLATE.format(*cl_format))
    commits.append(_CQ_TEMPLATE.format(*cl_format))
    abandons.append(_ABANDON_TEMPLATE.format(*cl_format))
  if not reviews:  # pragma: nocover
    return None
  commands = 'Review commands:\n' + '\n'.join(reviews)
  commands += '\n\nVerify commands:\n' + '\n'.join(verifies)
  commands += '\n\nCommit commands:\n' + '\n'.join(commits)
  commands += '\n\nAbandon commands:\n' + '\n'.join(abandons)
  return commands


def _has_changes_on_host(changes: List[GerritChange], host: str) -> bool:
  """Returns whether the changes have a change on host.

  Returns whether or not the list of changes have a change that is on the
  give gerrit host.

  Args:
    changes: List of generated gerrit changes.
    host: Host to check.

  Returns:
    bool whether or not the changes have a change on host.
  """
  for change in changes:
    if host in change.host:
      return True
  return False


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  message_template = '''Regenerate audio config in project {project}.

Regenerate the audio config in project {project}
per the changes in program galaxy.

BUG=https://crbug.com/1087514
TEST=CQ
'''
  cls = [
      common_pb2.GerritChange(host='chromium-review.googlesource.com',
                              project='chromiumos/config', change=1234),
      common_pb2.GerritChange(host='chrome-internal-review.googlesource.com',
                              project='chromeos/program/galaxy', change=1234),
  ]

  def build(changes=True):
    build_message = api.buildbucket.ci_build_message(project='chromeos',
                                                     bucket='infra',
                                                     builder='cl_factory')
    if changes:
      build_message.input.gerrit_changes.extend(cls)

    return api.buildbucket.build(build_message)

  def forall_data(*projects):
    """Returns a generator for project_infos_step_data."""
    return ({'project': p} for p in projects)

  def no_git_diff_step_data(project):
    step_name = 'generate project change lists.working on project {}.git status'
    return api.step_data(
        step_name.format(project), stdout=api.raw_io.output(''))

  yield api.test(
      'with-diff',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              ccs=['bob@google.com', 'martin@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
              manifest_branch='release-R12-34567.B',
          )),
  )

  yield api.test(
      'set-source-depends',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              ccs=['bob@google.com', 'martin@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
              set_source_depends=True,
          )),
  )

  yield api.test(
      'without-diff',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      no_git_diff_step_data('project-a'),
      no_git_diff_step_data('project-b'),
      no_git_diff_step_data('project-c'),
  )

  yield api.test(
      'with-replace-strings',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
              replace_strings=[
                  ClFactoryProperties.ReplaceString(
                      file_glob='*.star',
                      before='o',
                      after='X',
                  )
              ],
          )),
  )

  # Users may want to only replace strings, with no gerrit changes inputs
  # specified.
  yield api.test(
      'no-gerrit-changes-specified',
      build(changes=False),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
              replace_strings=[
                  ClFactoryProperties.ReplaceString(
                      file_glob='*.star',
                      before='1345.6',
                      after='1421.9',
                  )
              ],
          )),
  )

  yield api.test(
      'with-full-sync',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
              full_repo_sync=True,
          )),
  )

  # Here we replace the canned forall return to exercise the set logic
  # that determines repos to sync in a partial sync.
  yield api.test(
      'with-partial-sync-set-logic',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.repo.project_infos_step_data('find gerrit change repos',
                                       forall_data('a', 'b')),
      api.repo.project_infos_step_data('find regex matching CL repos',
                                       forall_data('c', 'd')),
      api.repo.project_infos_step_data('find additional repos to sync',
                                       forall_data('c', 'e')),
  )

  # Here we replace the canned forall return to simulate the user providing
  # a regex that didn't match anything.
  yield api.test(
      'bad-regex', build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.repo.project_infos_step_data('find gerrit change repos',
                                       forall_data('a', 'b')),
      api.repo.project_infos_step_data('find regex matching CL repos', {}),
      api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*No matching projects.*'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'invalid-message-template-interpolation',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template='No such {interpolation}.',
          )),
  )

  yield api.test(
      'no-repos-specified',
      build(),
      api.properties(
          ClFactoryProperties(
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*Projects to operate on must be specified.*'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'no-message-template-specified',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*A message_template property must specify.*'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )
