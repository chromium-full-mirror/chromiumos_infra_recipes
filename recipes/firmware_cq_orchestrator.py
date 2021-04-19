# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'bot_cost',
    'cros_infra_config',
    'easy',
    'gerrit',
    'orch_menu',
    'src_state',
    'test_util',
]

import re

from recipe_engine.recipe_api import StepFailure
from recipe_engine.post_process import (PropertyEquals, StatusSuccess,
                                        StatusFailure)


def RunSteps(api):
  branch_fmt = (r'(?P<base>firmware-'
                r'(?P<device>[-a-z_0-9.]+)-'
                r'(?P<version>[0-9.]+)'
                r')\.B'
                r'(?P<branch>-.+)?$')
  valid_branch = lambda b: re.match(branch_fmt, b)

  with api.bot_cost.build_cost_context():
    with api.step.nest('determine branch') as presentation:
      patch_sets = api.gerrit.fetch_patch_sets(api.src_state.gerrit_changes)
      branches = set(x.branch for x in patch_sets)
      branch = list(branches).pop(0)
      # Consider adding support for branch="main" to run snapshot builder(s).
      if len(branches) != 1 or not valid_branch(branch):
        raise StepFailure('Expected valid firmware branch, got: {}'.format(
            ' '.join(branches)))
      api.easy.set_properties_step(manifest_branch=branch)
      presentation.step_text = branch

    commit = api.src_state.gitiles_commit
    # If the builder was not run with a commit, point to the correct branch.
    if not commit.project:
      commit = api.src_state.internal_manifest.as_gitiles_commit_proto
      commit.ref = 'refs/heads/{}'.format(branch)
    api.cros_infra_config.configure_builder(commit=commit)

    # Turn the branch name into the cq builder name.
    builder = re.sub(branch_fmt, r'\g<base>-cq', branch)
    api.easy.set_properties_step(child_verifier=builder)
    child_config = api.cros_infra_config.get_builder_config(
        builder, missing_ok=True)
    if child_config:
      api.orch_menu.schedule_wait_build(builder, await_completion=True,
                                        check_failures=True,
                                        step_name='launch child')
    else:
      with api.step.nest('launch child') as pres:
        pres.step_text = 'Builder {} is not configured'.format(builder)

    return api.orch_menu.create_recipe_result()


def GenTests(api):

  test_base = 'firmware-board-5555'
  test_branch = '{}.B'.format(test_base)
  test_builder = '{}-cq'.format(test_base)

  def test(name, statuscheck, *args, **kwargs):
    kwargs.setdefault('cq', True)
    kwargs.setdefault('critical', True)
    kwargs.setdefault('builder', 'firmware-cq-orchestrator')
    branch = kwargs.pop('branch', test_branch)
    orch = api.test_util.test_orchestrator(**kwargs)
    changes = orch.message.input.gerrit_changes

    values = {x.change: {"branch": branch} for x in changes}
    args += (orch.build, api.post_check(statuscheck),
             api.gerrit.set_gerrit_fetch_changes_response(
                 'determine branch', changes, values))
    return api.test(name, *args)

  yield test('cq', StatusSuccess,
             api.post_check(PropertyEquals, 'manifest_branch', test_branch),
             api.post_check(PropertyEquals, 'child_verifier', test_builder))

  yield test(
      'cq-tagged', StatusSuccess,
      api.post_check(PropertyEquals, 'manifest_branch',
                     '{}-main'.format(test_branch)),
      api.post_check(PropertyEquals, 'child_verifier', test_builder),
      branch='{}-main'.format(test_branch))

  yield test('bad-branch', StatusFailure, branch='bad')

  yield test(
      'failed-child', StatusFailure,
      api.buildbucket.simulated_collect_output([
          api.test_util.test_build(builder=test_builder, status='FAILURE',
                                   critical='YES').message
      ], step_name='launch child.collect'))

  yield test('no-child', StatusSuccess, branch='firmware-board-5556.B')
