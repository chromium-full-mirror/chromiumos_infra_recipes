# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Used to create sweeping changes by creating CLs in many repos.

This recipe is currently focused on the use case of running gen_config in
program and project repositories. Invocation is most easily handled via the
cl_factory script in the chromiumos/config repo's bin directory:

https://chromium.googlesource.com/chromiumos/config/+/refs/heads/master/bin/cl_factory

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

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.cl_factory import ClFactoryProperties

PROPERTIES = ClFactoryProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_cq_depends',
    'cros_sdk',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'repo',
]

_CHROMIOUS_CONFIG_PROJECT = 'chromiumos/config'
_CHANGE_ID_REGEX = re.compile(r'^Change-Id: ', re.MULTILINE)


def RunSteps(api, properties):
  _validate_inputs(properties)
  gerrit_changes = api.buildbucket.build.input.gerrit_changes

  with api.cros_source.checkout_overlays_context(), \
    api.context(cwd=api.cros_source.workspace_path):

    with api.step.nest('find gerrit change repos'):
      gc_infos = api.repo.project_infos([gc.project for gc in gerrit_changes])

    with api.step.nest('find regex matching CL repos'):
      cl_infos = api.repo.project_infos(regexes=list(properties.repo_regexes))
      if len(cl_infos) == 0:
        regexes = ', '.join(
            map(lambda v: '"{}"'.format(v), properties.repo_regexes))
        raise ValueError(
            'No matching projects found, for regex: {}'.format(regexes))

    with api.step.nest('find additional repos to sync'):
      sync_projects = _determine_sync_projects(api, gc_infos, cl_infos,
                                               properties)

    # TODO(https://crbug.com/1101452): Note the cache_path_override in the sync.
    # Syncs to the cache are not always being reflected in the workspace. To
    # avoid this issue we sync to the workspace itself.

    api.cros_source.ensure_synced_cache(
        init_opts=dict(verbose=True), sync_opts=dict(verbose=True),
        cache_path_override=api.cros_source.workspace_path,
        projects=sync_projects)

    with api.step.nest('cherry-pick gerrit changes'):
      patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
      api.cros_source.apply_gerrit_patch_sets(patch_sets)

    # Start development branches for each project.
    api.repo.start('cl-factory', projects=[info.name for info in cl_infos])

    with api.step.nest('generate project change lists') as pres:
      changes, diffs = _make_changes(api, cl_infos, gerrit_changes, properties)
      if changes:
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


def _validate_inputs(properties):
  """Validates the inputs to this recipe.

  Validates that the inputs to this recipe. An exception is thrown if a problem
  is found.

  Args:
    properties (ClFactoryProperties): recipe input properties.
  """
  if not properties.repo_regexes:
    raise ValueError(
        'Projects to operate on must be specified by the '
        'repo_regexes property.')

  if not properties.message_template:
    raise ValueError(
        'A message_template property must specify how to create '
        'commit messages')


def _make_changes(api, cl_infos, gerrit_changes, properties):
  """Creates and returns the generated change lists and their diffs

  Args:
    api (RecipeApi): See RunSteps documentation.
    cl_infos (List[ProjectInfo]}: List of infos for the projects CLs are being
      made in. Corresponds to that found via repo_regexes.
    gerrit_changes (List[GerritChange]): gerrit change inputs to the recipe.
    properties (ClFactoryProperties): Input properties to the recipe.

  Returns:
    (List([GerritChange]), List([str])) tuple of generated changes and the diffs
      for those changes
  """
  diffs = []
  changes = []
  for info in cl_infos:
    with api.step.nest('working on project {}'.format(info.name)) as pres, \
        api.context(cwd=api.cros_source.workspace_path.join(info.path)):

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


def _make_cl(api, info, properties, gerrit_changes):
  """Makes and returns a generated gerrit change and their diffs.

  Makes and returns a generated gerrit change, assumes cwd is the project path.

  Args:
    api (RecipeApi): See RunSteps documentation.
    info (ProjectInfo): project info of project making a change list for.
    properties (ClFactoryProperties): recipe input properties.
    gerrit_changes (List[GerritChange]): gerrit change inputs to the recipe.

  Returns:
    (List([GerritChange]), List([str])) tuple of generated changes and the diffs
      for those changes
  """
  project_path = api.context.cwd
  commit_message = _make_commit_message(api, info, gerrit_changes, properties)
  api.git.add([project_path])
  test_stdout = '- before text\n+ after text'
  diff = api.easy.stdout_step('grab a diff', ['git', 'diff', '--cached'],
                              test_stdout=test_stdout)
  api.git.commit(commit_message)
  cl = api.gerrit.create_change(
      project=project_path,
      reviewers=list(properties.reviewers),
      ccs=list(properties.ccs),
      hashtags=list(properties.hashtags),
  )
  return cl, diff


def _set_source_cq_depends(api, changes, gc_infos, gerrit_changes):
  """Sets Cq-Depend on the input gerrit changes.

  Args:
    api (RecipeApi): See RunSteps documentation.
    changes (List[GerritChange]): List of generated gerrit changes.
    gc_infos (List[ProjectInfo]): List of infos for the input gerrit changes.
    gerrit_changes (List[GerritChange]): gerrit change inputs to the recipe.
  """
  cq_depend = api.cros_cq_depends.get_cq_depend(changes)
  replacement = cq_depend + '\nChange-Id: '

  with api.step.nest('applying Cq-Depend to input projects'):
    for info, change in zip(gc_infos, gerrit_changes):
      with api.step.nest('applying Cq-Depend to {}'
                         .format(info.name)) as pres, \
          api.context(cwd=api.cros_source.workspace_path.join(info.path)):

        # For the change description commands to work we must be operating
        # on a tracking branch.
        api.step('create cl_factory branch', [
            'git', 'checkout', '-b', '__cl_factory', '--track', '{}/{}'.format(
                info.remote, 'master')
        ])
        description = api.gerrit.get_change_description(change)
        description = re.sub(_CHANGE_ID_REGEX, replacement, description)
        api.gerrit.set_change_description(change, description)


def _determine_sync_projects(api, gc_infos, cl_infos, properties):
  """Determines projects needing to be synced and returns them.

  Args:
    api (RecipeApi): See RunSteps documentation.
    gc_infos (List[ProjectInfo]): List of infos for the input gerrit changes.
    cl_infos (List[ProjectInfo]}: List of infos for the projects CLs are being
      made in. Corresponds to that found via repo_regexes.
    properties (ClFactoryProperties): Input properties to the recipe.

  Returns:
    List([str]) of projects to sync, returning an empty list to sync all.
  """
  if properties.full_repo_sync:
    return []
  # For now since this only does gen_config we are assuming as such.
  # Thus make sure that all projects that could be involved in config generation
  # are up to date even when not specified by gerrit changes or repos to make
  # CLs in. This would include chromiumos/config and all program repos.
  projects = set([i.name for i in gc_infos + cl_infos])
  projects.add(_CHROMIOUS_CONFIG_PROJECT)
  program_infos = api.repo.project_infos(regexes=['chromeos/program'])
  projects.update(set([i.name for i in program_infos]))
  return list(projects)


def _replace_strings(api, properties):
  """Executes string replacements with cwd repo.

  Args:
    api (RecipeApi): See RunSteps documentation.
    properties (ClFactoryProperties): recipe input properties.
  """
  with api.step.nest('replace_strings'):
    for rs in properties.replace_strings:
      for filename in api.file.glob_paths('find replace string files',
                                          api.context.cwd, rs.file_glob,
                                          test_data=['file.txt', 'file.star']):
        filedata = api.file.read_raw('read {}'.format(filename), filename,
                                     test_data='hello world')
        filedata = filedata.replace(rs.before, rs.after)
        api.file.write_raw('write {}'.format(filename), filename, str(filedata))


def _gen_config(api):
  """Executes gen_config within cwd device configuration repo.

  Executes gen_config within the cwd device configuration repo. If gen_config or
  config.star are not found in the usual locations this step will ignore this
  repo. This is handy because the chromeos/project/private repo, for example, is
  not a regular device configuration repo but the easy regex, "src/project",
  will of course hit it.

  Args:
    api (RecipeApi): See RunSteps documentation.
  """
  gen_config_path = api.context.cwd.join('config', 'bin', 'gen_config')
  config_path = api.context.cwd.join('config.star')

  api.path.mock_add_paths(gen_config_path)
  api.path.mock_add_paths(config_path)

  with api.step.nest('gen_config') as pres:
    if (not api.path.exists(gen_config_path) or
        not api.path.exists(config_path)):  # pragma: nocover
      pres.step_text = 'gen_config files not found'
    else:
      api.step('run gen_config config.star', [gen_config_path, config_path])


def _make_commit_message(api, info, gerrit_changes, properties):
  """Makes the commit message for a generated gerrit change.

  Args:
    api (RecipeApi): See RunSteps documentation.
    info (ProjectInfo): project info of project making a commit message for.
    gerrit_changes (List[GerritChange]): gerrit change inputs to the recipe.
    properties (ClFactoryProperties): Input properties to the recipe.

  Returns:
    str commit message.
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
  message += '\n\n{}'.format(api.cros_cq_depends.get_cq_depend(gerrit_changes))
  return message


def _make_unified_diff(changes, diffs):
  """Makes a unified, single string, concatenation of all the diffs.

  Combines the given diffs into a single string with a small header that shows
  what project each particular diff comes from. The intention is for the user
  to get an overall view of what has changed and thus may be able to make an
  overall approval decision without visiting each change in gerrit.

  Args:
    changes (List[GerritChange]): List of generated gerrit changes.
    diffs (List[str]): List of diffs for the generated gerrit changes.

  Returns:
    str unified diff.
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


def _make_gerrit_commands(api, hashtags, changes):
  """Returns a the gerrit commands to review, verify, commit the changes.

  Returns a string containing the gerrit command line commands that can be used
  to review, verify, and commit the changes.

  Args:
    api (RecipeApi): See RunSteps documentation.
    hashtags (List[str]): List of hashtags applied to generated gerrit changes.
    changes (List[GerritChange]): List of generated gerrit changes.

  Returns:
    str of approval commands suitable for presenting to the user, or None
      if no commands could be determined.
  """
  owner_constraint = 'owner:{}'.format(
      api.buildbucket.build.infra.swarming.task_service_account)
  hashtag_constraints = ' '.join(
      map(lambda t: 'hashtag:{}'.format(t), hashtags))
  reviews = []
  verifies = []
  commits = []
  abandons = []
  if _has_changes_on_host(changes, 'chromium-review.googlesource.com'):
    format = ['', owner_constraint, hashtag_constraints]
    reviews.append(_CR_TEMPLATE.format(*format))
    verifies.append(_V_TEMPLATE.format(*format))
    commits.append(_CQ_TEMPLATE.format(*format))
    abandons.append(_ABANDON_TEMPLATE.format(*format))
  if _has_changes_on_host(
      changes, 'chrome-internal-review.googlesource.com'):  # pragma: nocover
    format = ['-i', owner_constraint, hashtag_constraints]
    reviews.append(_CR_TEMPLATE.format(*format))
    verifies.append(_V_TEMPLATE.format(*format))
    commits.append(_CQ_TEMPLATE.format(*format))
    abandons.append(_ABANDON_TEMPLATE.format(*format))
  if not reviews:  # pragma: nocover
    return None
  commands = 'Review commands:\n' + '\n'.join(reviews)
  commands += '\n\nVerify commands:\n' + '\n'.join(verifies)
  commands += '\n\nCommit commands:\n' + '\n'.join(commits)
  commands += '\n\nAbandon commands:\n' + '\n'.join(abandons)
  return commands


def _has_changes_on_host(changes, host):
  """Returns whether the changes have a change on host.

  Returns whether or not the list of changes have a change that is on the
  give gerrit host.

  Args:
    changes (List[GerritChange]): List of generated gerrit changes.
    host (str): Host to check.

  Returns:
    bool whether or not the changes have a change on host.
  """
  for change in changes:
    if host in change.host:
      return True
  return False


def GenTests(api):
  message_template = """Regenerate audio config in project {project}.

Regenerate the audio config in project {project}
per the changes in program galaxy.

BUG=https://crbug.com/1087514
TEST=CQ
"""
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

  def forall_output(*projects):
    return '\n'.join(
        '{0}|src/{0}|cros|refs/heads/master|refs/heads/master'.format(p)
        for p in projects)

  def no_git_diff_step_data(project):
    step_name = 'generate project change lists.working on project {}.git status'
    return api.step_data(
        step_name.format(project), stdout=api.raw_io.output(''))

  yield api.test(
      'with_diff',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              ccs=['bob@google.com', 'martin@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'without_diff',
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
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'with_replace_strings',
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
      api.post_check(post_process.StatusSuccess),
  )

  # Users may want to only replace strings, with no gerrit changes inputs
  # specified.
  yield api.test(
      'no_gerrit_changes_specified',
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
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'with_full_sync',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
              full_repo_sync=True,
          )),
      api.post_check(post_process.StatusSuccess),
  )

  # Here we replace the canned forall return to exercise the set logic
  # that determines repos to sync in a partial sync.
  yield api.test(
      'with_partial_sync_set_logic',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.step_data('find gerrit change repos.repo forall',
                    stdout=api.raw_io.output(forall_output('a', 'b'))),
      api.step_data('find regex matching CL repos.repo forall',
                    stdout=api.raw_io.output(forall_output('c', 'd'))),
      api.step_data('find additional repos to sync.repo forall',
                    stdout=api.raw_io.output(forall_output('c', 'e'))),
      api.post_check(post_process.StatusSuccess),
  )

  # Here we replace the canned forall return to simulate the user providing
  # a regex that didn't match anything.
  yield api.test(
      'bad_regex',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.step_data('find gerrit change repos.repo forall',
                    stdout=api.raw_io.output(forall_output('a', 'b'))),
      api.step_data('find regex matching CL repos.repo forall',
                    stdout=api.raw_io.output('')),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE, '.*No matching projects.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'invalid_message_template_interpolation',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template='No such {interpolation}.',
          )),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'no_repos_specified',
      build(),
      api.properties(
          ClFactoryProperties(
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*Projects to operate on must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_message_template_specified',
      build(),
      api.properties(ClFactoryProperties(
          repo_regexes = ['src/project/galaxy'],
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
      )),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          '.*A message_template property must specify.*'),
      api.post_process(post_process.DropExpectation),
  )
