# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Copybot.

This recipe calls the RunCopybot endpoint from the Build API CopybotService.
"""

from PB.go.chromium.org.luci.buildbucket.proto import (
    common as buildbucket_common,)
from PB.recipe_engine.result import RawResult
from PB.recipes.chromeos.copybot import CopybotProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    "recipe_engine/buildbucket",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/runtime",
    "recipe_engine/step",
    "recipe_engine/time",
    "build_menu",
    "cros_build_api",
    "easy",
    "git",
    "src_state",
]


PROPERTIES = CopybotProperties


def RunSteps(api: RecipeApi, properties: CopybotProperties):
  with api.build_menu.configure_builder(missing_ok=True):
    # Clone copybot repo to infra/copybot
    copybot_dir = api.src_state.workspace_path / "infra" / "copybot"
    api.git.clone(
        "https://chromium.googlesource.com/copybot",
        target_path=copybot_dir,
    )
    infra_dir = api.src_state.workspace_path / "infra"
    api.step(
        "create copybot path compatibility symlink",
        ["ln", "-sfn", ".", infra_dir / "infra"],
    )
    return run_copybot(api, properties)


def run_copybot(api: RecipeApi, properties: CopybotProperties):
  """Call the RunCopybot endpoint."""
  with api.step.nest("Run Copybot") as presentation:
    retcode = -1

    def set_retcode(result):
      nonlocal retcode
      retcode = result

    properties.request.build_id = str(api.buildbucket.build.id)
    properties.request.build_url = api.buildbucket.build_url()
    if properties.request.git_dir:
      properties.request.git_dir = str(
          api.path.cache_dir.joinpath(properties.request.git_dir))
    response = api.cros_build_api.CopybotService.RunCopybot(
        properties.request,
        retcode_fn=set_retcode,
        skip_endpoint_retrieval=True,
    )
    presentation.properties["copybot_response"] = response
    if retcode != 0:
      raise api.step.StepFailure(
          f"Run Copybot Failed (return code {retcode})\n{response.summary_markdown}"
      )
    return RawResult(
        summary_markdown=response.summary_markdown,
        status=buildbucket_common.Status.SUCCESS,
    )


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      "success",
      api.post_check(
          post_process.StepSuccess,
          "Run Copybot.call chromite.api.CopybotService/RunCopybot",
      ),
  )

  yield api.build_menu.test(
      "success_with_git_dir",
      api.properties(request={'git_dir': 'some_git_dir'}),
      api.post_check(
          post_process.StepSuccess,
          "Run Copybot.call chromite.api.CopybotService/RunCopybot",
      ),
  )

  yield api.build_menu.test(
      "success_with_warning",
      api.build_menu.set_build_api_return(
          "Run Copybot",
          "CopybotService/RunCopybot",
          retcode=0,
          data='{ "summary_markdown": "Warning: 1234 commits not yet uploaded" }',
      ),
      api.post_check(
          post_process.StepSuccess,
          "Run Copybot.call chromite.api.CopybotService/RunCopybot",
      ),
      api.post_process(post_process.SummaryMarkdown,
                       'Warning: 1234 commits not yet uploaded'),
  )

  yield api.build_menu.test(
      "service-endpoint-failure-response-available",
      api.build_menu.set_build_api_return(
          "Run Copybot",
          "CopybotService/RunCopybot",
          retcode=2,
          data='{ "failure_reason": "FAILURE_DOWNSTREAM_PUSH_ERROR" }',
      ),
      api.post_check(
          post_process.StepFailure,
          "Run Copybot.call chromite.api.CopybotService/RunCopybot",
      ),
      status="FAILURE",
  )

  yield api.build_menu.test(
      "service-endpoint-failure-no-response",
      api.build_menu.set_build_api_return(
          "Run Copybot",
          "CopybotService/RunCopybot",
          retcode=1,
      ),
      api.post_check(
          post_process.StepFailure,
          "Run Copybot.call chromite.api.CopybotService/RunCopybot",
      ),
      status="FAILURE",
  )
