# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format
from PB.recipe_modules.chromeos.repo.examples.branching import BranchingProperties
from PB.recipe_modules.chromeos.repo.examples.branching import BranchProjects

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'repo',
]


PROPERTIES = BranchingProperties


def RunSteps(api, properties):
  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  with api.context(cwd=repo_root):
    sync_opts = json_format.MessageToDict(properties.sync_opts,
                                          preserving_proto_field_name=True)
    api.repo.sync_manifest(properties.manifest_url, properties.manifest_data,
                           **sync_opts)

    if properties.HasField('start_args'):
      projects = (
          None if properties.start_args.all_projects else
          properties.start_args.projects)
      api.repo.start(properties.start_args.branch, projects=projects)

    if properties.HasField('abandon_args'):
      projects = (
          None if properties.abandon_args.all_projects else
          properties.abandon_args.projects)
      api.repo.abandon(properties.abandon_args.branch, projects=projects)


def GenTests(api):

  def verify_step_cmd(check, steps, name, cmd_args):
    return check(steps[name].cmd[1:] == cmd_args)

  yield api.test(
      'branch-no-projects',
      api.properties(
          BranchingProperties(
              start_args=BranchProjects(branch='no-projects',
                                        all_projects=True),
              abandon_args=BranchProjects(branch='no-projects',
                                          all_projects=True),
          )),
      api.post_check(verify_step_cmd, 'repo start',
                     ['start', 'no-projects', '--all']),
      api.post_check(verify_step_cmd, 'repo abandon',
                     ['abandon', 'no-projects', '--all']))

  yield api.test(
      'branch-with-projects',
      api.properties(
          BranchingProperties(
              start_args=BranchProjects(branch='with-projects',
                                        projects=['project']),
              abandon_args=BranchProjects(branch='with-projects',
                                          projects=['project']),
          )),
      api.post_check(verify_step_cmd, 'repo start',
                     ['start', 'with-projects', 'project']),
      api.post_check(verify_step_cmd, 'repo abandon',
                     ['abandon', 'with-projects', 'project']))

  yield api.test(
      'branch-empty-projects',
      api.properties(
          BranchingProperties(
              start_args=BranchProjects(branch='empty-projects', projects=[]),
              abandon_args=BranchProjects(branch='empty-projects', projects=[]),
          )),
      api.post_check(verify_step_cmd, 'repo start',
                     ['start', 'empty-projects']),
      api.post_check(verify_step_cmd, 'repo abandon',
                     ['abandon', 'empty-projects']))
