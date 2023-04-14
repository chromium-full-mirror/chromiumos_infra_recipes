# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that handle_open_changes() runs the expected process."""
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import GerritChange
from PB.chromiumos.common import PackageInfo
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import NO_RETRY
from PB.recipes.chromeos.generator import OUTDATED_ABANDON
from PB.recipes.chromeos.generator import OUTDATED_LEAVE_COMMENT
from PB.recipes.chromeos.generator import RETRY_LATEST_PINNED
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine.recipe_api import Property

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
    'gerrit',
    'git',
    'pupr_gerrit_interface',
    'pupr_local_uprev',
    'src_state',
    'test_util',
]

PROPERTIES = {
    'outdated_cls_policy': Property(),
    'expected': Property(default=True),
    'retry_only': Property(default=False),
    'changes': Property(default=1),
}

BUILD_TARGETS = [BuildTarget(name='build-target')]
PACKAGE_CHROME = PackageInfo(category='chromeos-base',
                             package_name='chromeos-chrome')
PACKAGES = [PACKAGE_CHROME]


def RunSteps(api: recipe_api.RecipeApi, outdated_cls_policy: any,
             expected: bool, retry_only: bool, changes: int):
  # Arrange
  api.pupr_local_uprev.set_generator_attributes(
      packages=PACKAGES,
      build_targets=BUILD_TARGETS,
  )

  mrm = api.pupr_gerrit_interface.find_most_recently_merged_uprev(
      {
          'cros': [
              ProjectInfo(name='galaxy', path='project', remote='cros',
                          branch=f'{api.src_state.workspace_path}',
                          rrev=api.src_state.workspace_path)
          ]
      }, 'topic') if changes > 0 else None
  api.assertions.assertEqual(
      expected,
      api.pupr_gerrit_interface.handle_outdated_changes(
          [
              GerritChange(host='chromium-review.googlesource.com',
                           change=1234 + i) for i in range(0, changes)
          ], mrm,
          BranchPolicy(pattern='.*', repl='',
                       reviewers=[Reviewer(email='a@example.com')
                                 ], no_existing_cls_policy=FULL_RUN,
                       existing_cls_policy=SUBMIT,
                       retry_cl_policy=RETRY_LATEST_PINNED,
                       outdated_cls_policy=outdated_cls_policy), retry_only))


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      'basic', api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'outdated-abandon',
      api.properties(outdated_cls_policy=OUTDATED_ABANDON, expected=False),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.comment on CL 1234'
      ),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_ABANDON.abandon CL 1234'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-rebase',
      api.properties(existing_cls_policy=SUBMIT,
                     no_existing_cls_policy=FULL_RUN, retry_cl_policy=NO_RETRY,
                     outdated_cls_policy=OUTDATED_LEAVE_COMMENT),
      api.post_check(post_process.MustRun, 'outdated CLs'),
      api.post_check(
          post_process.MustRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.comment on CL 1234'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'act on outdated CLs with policy: OUTDATED_LEAVE_COMMENT.abandon CL 1234'
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-recent-merged-cl',
      api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT, expected=False,
                     changes=0), api.post_process(post_process.DropExpectation))
