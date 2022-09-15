# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'repo',
]

import six

from google.protobuf import json_format

from PB.recipe_modules.chromeos.repo.examples.branching import (
    BranchingProperties, BranchProjects)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = BranchingProperties


def RunSteps(api, properties):
  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  with api.context(cwd=repo_root):
    sync_opts = json_format.MessageToDict(properties.sync_opts,
                                          preserving_proto_field_name=True)
    api.repo.sync_manifest(properties.manifest_url,
                           six.ensure_str(properties.manifest_data),
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
      'branch-no-projects-manifest-depth',
      api.properties(
          BranchingProperties(
              start_args=BranchProjects(branch='no-projects',
                                        all_projects=True),
              abandon_args=BranchProjects(branch='no-projects',
                                          all_projects=True),
          )),
      api.step_data(
          'check if repo version is at least 2.29.repo version',
          stdout=api.raw_io.output_text("""repo version v2.29-cr1
        (from https://chromium.googlesource.com/external/repo)
        (tracking refs/heads/main)
        (Tue, 23 Aug 2022 11:20:59 -0400)
 repo launcher version 2.29
        (from /b/s/w/ir/kitchen-checkout/depot_tools/repo_launcher)
        (currently at 2.29-cr1)
 repo User-Agent git-repo/2.29-cr1 (Linux) git/2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C) Python/3.8.10
 git 2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C)
 git User-Agent git/2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C) (Linux) git-repo/2.29-cr1
 Python 3.8.10+chromium.23 (default, Nov 11 2021, 05:59:41) 
 [GCC 10.2.1 20210130 (Red Hat 10.2.1-11)]
 OS Linux 5.4.0-125-generic (#141~18.04.1-Ubuntu SMP Thu Aug 11 20:15:56 UTC 2022)
 CPU x86_64 (x86_64)
 Bug reports: https://bugs.chromium.org/p/gerrit/issues/entry?template=Repo+tool+issue"""
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
