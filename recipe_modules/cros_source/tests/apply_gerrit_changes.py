# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from RECIPE_MODULES.chromeos.cros_source.test_utils import GitStrategyEquals

from PB.recipe_modules.chromeos.cros_source.cros_source import GitStrategy
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_source',
    'repo',
    'src_state',
]



def RunSteps(api):
  api.cros_source.apply_gerrit_changes(api.src_state.gerrit_changes)


def GenTests(api):

  manifest_branch = 'snapshot'
  yield api.cros_source.test(
      'apply-gerrit-changes-fail',
      manifest_branch,
      api.repo.fail_repo_sync(True),
      api.post_check(GitStrategyEquals, GitStrategy.CHERRY_PICK),
      status='INFRA_FAILURE',
  )

  yield api.cros_source.test(
      'apply-gerrit-changes-success',
      manifest_branch,
      api.post_check(GitStrategyEquals, GitStrategy.CHERRY_PICK),
  )

  yield api.cros_source.test(
      'cherry-pick-success',
      manifest_branch,
      api.buildbucket.try_build(),
      api.post_check(post_process.MustRun,
                     'apply gerrit patch sets.git cherry-pick'),
      api.post_check(post_process.DoesNotRun,
                     'apply gerrit patch sets.git cherry-pick --abort'),
      api.post_check(post_process.DoesNotRun,
                     'apply gerrit patch sets.git merge'),
      api.post_check(GitStrategyEquals, GitStrategy.CHERRY_PICK),
      api.post_process(post_process.DropExpectation),
  )

  yield api.cros_source.test(
      'cherry-pick-fail',
      manifest_branch,
      api.buildbucket.try_build(),
      api.step_data('apply gerrit patch sets.git cherry-pick', retcode=1),
      api.post_check(post_process.MustRun,
                     'apply gerrit patch sets.git cherry-pick'),
      api.post_check(post_process.MustRun,
                     'apply gerrit patch sets.git cherry-pick --abort'),
      api.post_check(post_process.MustRun, 'apply gerrit patch sets.git merge'),
      api.post_check(GitStrategyEquals, GitStrategy.MERGE),
      api.post_process(post_process.DropExpectation),
  )

  yield api.cros_source.test(
      'cherry-pick-fail-merge-fail',
      manifest_branch,
      api.buildbucket.try_build(),
      api.step_data('apply gerrit patch sets.git cherry-pick', retcode=1),
      api.step_data('apply gerrit patch sets.git merge', retcode=1),
      api.post_check(post_process.MustRun,
                     'apply gerrit patch sets.git cherry-pick'),
      api.post_check(post_process.MustRun,
                     'apply gerrit patch sets.git cherry-pick --abort'),
      api.post_check(post_process.MustRun, 'apply gerrit patch sets.git merge'),
      api.post_check(post_process.DoesNotRun,
                     'apply gerrit patch sets.set cros_source_git_strategy'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
