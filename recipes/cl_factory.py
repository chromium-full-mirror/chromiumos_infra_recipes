# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Used to create sweeping changes by creating CLs in many repos."""

import re

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.cl_factory import ClFactoryProperties

PROPERTIES = ClFactoryProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_cq_depends',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'repo',
]

_CHROMIOUS_CONFIG_PROJECT = 'chromiumos/config'
_CHANGE_ID_REGEX = re.compile(r'^Change-Id: ', re.MULTILINE)


def RunSteps(api, properties):
  gerrit_changes = api.buildbucket.build.input.gerrit_changes
  if not gerrit_changes:
    raise ValueError('Gerrit changes to apply must be specified.')

  if not properties.repo_regexes:
    raise ValueError(
        'Projects to operate on must be specified by the '
        'repo_regexes property.')

  if not properties.command:
    raise ValueError('A command property must specify how to modify the repos.')

  if not properties.message_template:
    raise ValueError(
        'A message_template property must specify how to create '
        'commit messages')

  with api.cros_source.checkout_overlays_context(), \
    api.context(cwd=api.cros_source.workspace_path):

    # The project infos for the the input gerrit changes and the projects infos
    # for the repos we are attempting to make changelists for.
    gc_infos = api.repo.project_infos([gc.project for gc in gerrit_changes])
    cl_infos = api.repo.project_infos(regexes=list(properties.repo_regexes))

    sync_projects = _determine_sync_projects(api, gc_infos, cl_infos,
                                             properties)
    api.cros_source.ensure_synced_cache(projects=sync_projects)

    with api.step.nest('cherry-pick gerrit changes'):
      patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
      api.cros_source.apply_gerrit_patch_sets(patch_sets)

    # Start development branches for each project.
    api.repo.start('cl-factory', projects=[info.name for info in cl_infos])

    changes = []
    for info in cl_infos:
      with api.step.nest('working on project {}'.format(info.name)) as pres, \
          api.context(cwd=api.cros_source.workspace_path.join(info.path)):

        _gen_config(api)

        if api.git.diff_check(api.context.cwd):
          pres.step_text = 'diff'
          cl = _make_cl(api, info, api.context.cwd, properties, gerrit_changes)
          changes.append(cl)
        else:
          pres.step_text = 'no diff'

    if changes:
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
                'git', 'checkout', '-b', '__cl_factory', '--track',
                '{}/{}'.format(info.remote, 'master')
            ])
            description = api.gerrit.get_change_description(change)
            description = re.sub(_CHANGE_ID_REGEX, replacement, description)
            api.gerrit.set_change_description(change, description)


def _determine_sync_projects(api, gc_infos, cl_infos, properties):
  """Determines projects needing to be synced and returns them.

  Args:
    api (RecipeApi): See RunSteps documentation.
    gc_infos (List[ProjectInfo]): List of infos for the gerrit changes.
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


def _gen_config(api):
  """Executes gen_config within cwd boxster repo.

  Args:
    api (RecipeApi): See RunSteps documentation.
  """
  gen_config_path = api.context.cwd.join('config', 'bin', 'gen_config')
  config_path = api.context.cwd.join('config.star')

  api.path.mock_add_paths(gen_config_path)
  api.path.mock_add_paths(config_path)

  if not api.path.exists(gen_config_path):  # pragma: nocover
    raise api.step.InfraFailure('gen_config not found. Expected at %s' %
                                gen_config_path)

  if not api.path.exists(config_path):  # pragma: nocover
    raise api.step.InfraFailure('config.star not found. Expected at %s' %
                                config_path)

  api.step('run gen_config config.star', [gen_config_path, config_path])


def _make_cl(api, info, project_path, properties, gerrit_changes):
  commit_message = _make_commit_message(api, info, properties, gerrit_changes)
  api.git.add([project_path])
  api.git.commit(commit_message)
  return api.gerrit.create_change(
      project=project_path,
      reviewers=list(properties.reviewers),
      hashtags=list(properties.hashtags),
  )


def _make_commit_message(api, info, properties, gerrit_changes):
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
  message += '\n\n{}'.format(api.cros_cq_depends.get_cq_depend(gerrit_changes))
  return message


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

  yield api.test(
      'with_diff',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              command='echo "hello world"',
              message_template=message_template,
          )),
      api.git.diff_check(True),
  )

  yield api.test(
      'without_diff',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              command='echo "hello world"',
              message_template=message_template,
          )),
  )

  yield api.test(
      'with_full_sync',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              command='echo "hello world"',
              message_template=message_template,
              full_repo_sync=True,
          )),
      api.git.diff_check(True),
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
              command='echo "hello world"',
              message_template=message_template,
          )),
      # Gerrit changes repos.
      api.step_data('repo forall',
                    stdout=api.raw_io.output(forall_output('a', 'b'))),
      # repo_regexes repos.
      api.step_data('repo forall (2)',
                    stdout=api.raw_io.output(forall_output('c', 'd'))),
      # Common boxster repos.
      api.step_data('repo forall (3)',
                    stdout=api.raw_io.output(forall_output('c', 'e'))),
      api.git.diff_check(True),
  )

  yield api.test(
      'invalid_message_template_interpolation',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              command='echo "hello world"',
              message_template='No such {interpolation}.',
          )),
      api.git.diff_check(True),
  )

  yield api.test(
      'no_gerrit_changes_specified',
      build(changes=False),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              command='echo "hello world"',
              message_template=message_template,
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*Gerrit changes to apply must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_repos_specified',
      build(),
      api.properties(
          ClFactoryProperties(
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              command='echo "hello world"',
              message_template=message_template,
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*Projects to operate on must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_command_specified',
      build(),
      api.properties(
          ClFactoryProperties(
              repo_regexes=['src/project/galaxy'],
              reviewers=['johndoe@google.com'],
              hashtags=['refactor-audio-config'],
              message_template=message_template,
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*A command property must specify.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_message_template_specified',
      build(),
      api.properties(ClFactoryProperties(
          repo_regexes = ['src/project/galaxy'],
          reviewers = ['johndoe@google.com'],
          hashtags = ['refactor-audio-config'],
          command = 'echo "hello world"',
      )),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          '.*A message_template property must specify.*'),
      api.post_process(post_process.DropExpectation),
  )
