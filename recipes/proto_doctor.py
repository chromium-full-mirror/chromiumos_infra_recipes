# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Compile and sync proto files across ChromeOS.

This recipe should normally be triggered via a gitiles_poller that watches for
changes to the infra/proto repo. The poller should batch requests, so there may
be several changes, which may be on different branches.
For more info on gitiles_pollers, see go/lucicfg#luci.gitiles_poller.
"""

from typing import Generator, List

from PB.chromite.api import api as api_service
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)
from recipe_engine import config_types
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/context',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'cros_build_api',
    'deferrals',
    'easy',
    'repo',
    'src_state',
]

# Repo projects
CHROMITE_REPO = 'chromiumos/chromite'
INFRA_PROTO_REPO = 'chromiumos/infra/proto'
CHROMITE_INFRA_PROTO_REPO = 'chromite/infra/proto'
PROJECTS_TO_CHECKOUT = (
    INFRA_PROTO_REPO,
    CHROMITE_REPO,
    CHROMITE_INFRA_PROTO_REPO,
)

# Branches and refs
MAIN_BRANCH = 'main'
MAIN_REF = 'refs/heads/main'


def RunSteps(api: recipe_api.RecipeApi) -> None:
  """Starting point for main recipe logic.

  This function does setup, determines which branches to work on, and then
  defers to child functions for specific processing.
  """
  gitiles_triggers = _validate_triggers(api)
  branches = sorted(set(_get_branch(gt) for gt in gitiles_triggers))
  api.easy.set_properties_step(branches=branches)

  # If one branch raises an exception, defer the exception so that the other
  # branches can run.
  with api.deferrals.raise_exceptions_at_end():
    for branch in branches:
      with api.deferrals.defer_exceptions():
        process_branch(api, branch)


def process_branch(api: recipe_api.RecipeApi, branch: str) -> None:
  """For a single branch, propagate infra/proto changes across the tree.

  Args:
    api: The recipe API.
    branch: The branch to work from, such as "main".
  """
  with api.step.nest(f'process branch {branch}'):
    check_out_branch(api, branch)
    compile_chromite_protos(api)


def check_out_branch(api: recipe_api.RecipeApi, branch: str) -> None:
  """Check out all the necessary projects on the given branch.

  Args:
    api: The recipe API.
    branch: The branch to checkout, such as "main".
  """
  with api.context(cwd=_get_checkout_path(api)):
    api.repo.init(
        manifest_url=api.src_state.internal_manifest.url,
        manifest_branch=branch,
    )
    api.repo.sync(projects=list(PROJECTS_TO_CHECKOUT))


def compile_chromite_protos(api: recipe_api.RecipeApi) -> None:
  """Compile proto bindings in chromite/, and upload to Gerrit."""
  with api.step.nest('compile chromite protos'):
    request = api_service.CompileProtoRequest()
    api.cros_build_api.ApiService.CompileProto(request)


def _validate_triggers(
    api: recipe_api.RecipeApi) -> List[triggers_pb2.GitilesTrigger]:
  """Verify that the build's triggers look OK.

  In general, this recipe should be triggered by Gitiles changes to the
  infra/proto repo.

  See https://go.chromium.org/luci/scheduler/api/scheduler/v1 for more info
  about triggers and the different trigger types.

  Returns:
    A list of GitilesTriggers that triggered this build.

  Raises:
    InfraFailure: If the build does not have any Gitiles triggers.
    InfraFailure: If any of the build's triggering CLs was from a repo besides
      infra/proto.
  """
  with api.step.nest('validate triggers'):
    gitiles_triggers: List[triggers_pb2.GitilesTrigger] = []
    for trigger in api.scheduler.triggers:
      if not trigger.HasField('gitiles'):
        continue
      if trigger.gitiles.repo != INFRA_PROTO_REPO:
        raise recipe_api.InfraFailure(
            f'Gitiles trigger in non-proto repo: {trigger}')
      gitiles_triggers.append(trigger.gitiles)
    if not gitiles_triggers:
      raise recipe_api.InfraFailure('No Gitiles triggers found')
    return gitiles_triggers


def _get_branch(gitiles_trigger: triggers_pb2.GitilesTrigger) -> str:
  """Return the branch that a GitilesTrigger was on."""
  return gitiles_trigger.ref.split('/')[-1]


def _get_checkout_path(api: recipe_api.RecipeApi) -> config_types.Path:
  """Return the path to the bot's local repo checkout."""
  return api.src_state.workspace_path


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Generate test cases for this recipe."""
  gitiles_trigger_main = triggers_pb2.GitilesTrigger(repo=INFRA_PROTO_REPO,
                                                     ref=MAIN_REF,
                                                     revision='aaaaaa')
  gitiles_trigger_main2 = triggers_pb2.GitilesTrigger(
      repo=INFRA_PROTO_REPO,
      ref=MAIN_REF,
      revision='bbbbbb',
  )
  release_branch = 'release-R100-14526.B'
  gitiles_trigger_release_branch = triggers_pb2.GitilesTrigger(
      repo=INFRA_PROTO_REPO, ref=f'refs/heads/{release_branch}',
      revision='cccccc')
  gitiles_trigger_chromite = triggers_pb2.GitilesTrigger(
      repo=CHROMITE_REPO,
      ref=MAIN_REF,
      revision='dddddd',
  )
  buildbucket_trigger = triggers_pb2.BuildbucketTrigger(tags=['a:b'])

  yield api.test(
      'basic',
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_release_branch),
          # Buildbucket trigger should be ignored.
          triggers_pb2.Trigger(buildbucket=buildbucket_trigger),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main2),
      ]),
      api.post_check(post_process.MustRun, f'process branch {MAIN_BRANCH}'),
      # Each branch should only be processed once, despite multiple triggers.
      api.post_check(post_process.DoesNotRun,
                     f'process branch {MAIN_BRANCH} (2)'),
      api.post_check(post_process.MustRun, f'process branch {release_branch}'),
  )

  yield api.test(
      'no-gitiles-triggers',
      api.scheduler(triggers=[
          triggers_pb2.Trigger(buildbucket=buildbucket_trigger),
      ]),
      api.post_check(post_process.StepException, 'validate triggers'),
      api.post_check(post_process.SummaryMarkdown, 'No Gitiles triggers found'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'non-proto-trigger',
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_chromite),
      ]),
      api.post_check(post_process.StepException, 'validate triggers'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Gitiles trigger in non-proto repo:.*'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'first-branch-fails-second-branch-runs',
      api.scheduler(triggers=[
          triggers_pb2.Trigger(gitiles=gitiles_trigger_main),
          triggers_pb2.Trigger(gitiles=gitiles_trigger_release_branch),
      ]),
      api.step_data('process branch main.repo init', retcode=1),
      # Double-check that the main branch comes before the release branch.
      api.post_check(post_process.PropertyEquals, 'branches',
                     [MAIN_BRANCH, release_branch]),
      api.post_check(post_process.StepException,
                     f'process branch {MAIN_BRANCH}'),
      api.post_check(post_process.StepSuccess,
                     f'process branch {release_branch}'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
