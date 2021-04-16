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
  with api.bot_cost.build_cost_context():
    with api.step.nest('determine branch') as presentation:
      patch_sets = api.gerrit.fetch_patch_sets(api.src_state.gerrit_changes)
      branches = set(x.branch for x in patch_sets)
      branch = list(branches).pop(0)
      # Consider adding support for branch="main" to run snapshot builder(s).
      if len(branches) != 1 or not branch.endswith('.B'):
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
    builder = re.sub(r'.B$', '-cq', branch)
    api.easy.set_properties_step(child_verifier=builder)
    api.orch_menu.schedule_wait_build(builder, await_completion=True,
                                      check_failures=True,
                                      step_name='launch child')

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

  yield test('bad-branch', StatusFailure, branch='bad')

  yield test(
      'failed-child', StatusFailure,
      api.buildbucket.simulated_collect_output([
          api.test_util.test_build(builder=test_builder, status='FAILURE',
                                   critical='YES').message
      ], step_name='launch child.collect'))
