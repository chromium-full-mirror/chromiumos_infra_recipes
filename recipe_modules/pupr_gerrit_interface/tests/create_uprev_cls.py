# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that create_uprev_cls() runs the expected process."""

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine import result
from PB.recipe_modules.chromeos.pupr_gerrit_interface.tests.tests import \
  CreateUprevClsProperties
from PB.recipes.chromeos.generator import ABANDON
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import DRY_RUN
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SUBMIT
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'gerrit',
    'pupr_gerrit_interface',
    'src_state',
]

PROPERTIES = CreateUprevClsProperties


def RunSteps(api: recipe_api.RecipeApi, properties: CreateUprevClsProperties):
  if properties.existing_cls:
    branch_policy = BranchPolicy(pattern='.*', repl='',
                                 reviewers=[Reviewer(email='a@example.com')],
                                 existing_cls_policy=properties.policy)
  else:
    branch_policy = BranchPolicy(pattern='.*', repl='',
                                 reviewers=[Reviewer(email='a@example.com')],
                                 no_existing_cls_policy=properties.policy)
  path_ = [
      ProjectInfo(name=f'galaxy{i}', path=f'project{i}', remote='cros',
                  branch=api.src_state.workspace_path,
                  rrev=api.src_state.workspace_path)
      for i in range(1, properties.projects + 1)
  ]

  summary = api.pupr_gerrit_interface.create_uprev_cls(path_, [],
                                                       properties.existing_cls,
                                                       branch_policy, 'a topic')
  return result.RawResult(status=common.SUCCESS, summary_markdown=summary)


def GenTests(api: recipe_test_api.RecipeTestApi):

  yield api.test(
      'submit', api.properties(policy=SUBMIT, projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Bot-Commit+1']),
      api.post_check(post_process.LogDoesNotContain,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Commit-Queue']),
      api.post_check(post_process.StepSuccess, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'dry-run', api.properties(policy=DRY_RUN, projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Bot-Commit+1']),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Commit-Queue+1']),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'dry-run-staging', api.properties(policy=DRY_RUN, projects=1),
      api.buildbucket.generic_build(project='chromeos', bucket='staging',
                                    builder='staging-my-cool-pupr-generator'),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.LogDoesNotContain,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Bot-Commit+1']),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Commit-Queue+1']),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'full-run', api.properties(policy=FULL_RUN, projects=2,
                                 existing_cls=True),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project2',
          'https://host-review.googlesource.com/c/project/+/456'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Bot-Commit+1']),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 123', 'labels',
                     ['Commit-Queue+2']),
      api.post_check(post_process.StepSuccess,
                     'update CL labels.set labels on CL 456'),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 456', 'labels',
                     ['Bot-Commit+1']),
      api.post_check(post_process.LogContains,
                     'update CL labels.set labels on CL 456', 'labels',
                     ['Commit-Queue+2']),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'abandon', api.properties(policy=ABANDON, projects=1),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://host-review.googlesource.com/c/project/+/123'),
      api.path.exists(api.src_state.workspace_path),
      api.post_check(post_process.DoesNotRun,
                     'update CL labels.set labels on CL 123'),
      api.post_check(post_process.DoesNotRun, 'update CL labels.submit CL'),
      api.post_check(post_process.MustRun, 'update CL labels.abandon CL 123'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'summary', api.properties(policy=FULL_RUN, projects=2, existing_cls=True),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project1',
          'https://chromium-review.googlesource.com/c/project/+/123'),
      api.gerrit.simulated_create_change(
          'generate CLs.create gerrit change for project2',
          'https://chrome-internal-review.googlesource.com/c/project/+/456'),
      api.path.exists(api.src_state.workspace_path),
      api.post_process(
          post_process.SummaryMarkdown,
          'created [chromium:123](https://crrev.com/c/123) '
          '[chrome-internal:456](https://crrev.com/i/456)'),
      api.post_process(post_process.DropExpectation))
