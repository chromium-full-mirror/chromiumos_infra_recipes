# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Qualbot.

This recipe calls the RunQualbot endpoint from the Build API QualbotService.
"""

from PB.recipes.chromeos.qualbot import QualbotProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'easy',
]

PROPERTIES = QualbotProperties


def RunSteps(api: RecipeApi, properties: QualbotProperties):
  api.cipd.ensure_tool('infra/3pp/tools/protoc/${platform}', "latest",
                       executable_path="bin/protoc")

  with api.build_menu.configure_builder(missing_ok=True), \
       api.build_menu.setup_workspace():
    run_qualbot(api, properties)


def run_qualbot(api: RecipeApi, properties: QualbotProperties):
  """Call the RunQualbot endpoint."""
  with api.step.nest('Run Qualbot') as presentation:
    retcode = -1

    def set_retcode(result):
      nonlocal retcode
      retcode = result

    properties.request.build_id = str(api.buildbucket.build.id)
    response = api.cros_build_api.QualbotService.RunQualbot(
        properties.request,
        retcode_fn=set_retcode,
    )
    presentation.properties['qualbot_response'] = response
    if retcode != 0:
      raise api.step.StepFailure(f'Run Qualbot Failed (return code {retcode})')


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'success',
      api.post_check(
          post_process.StepSuccess,
          'Run Qualbot.call chromite.api.QualbotService/RunQualbot',
      ),
  )

  yield api.build_menu.test(
      'service-endpoint-failure-response-available',
      api.build_menu.set_build_api_return(
          'Run Qualbot',
          'QualbotService/RunQualbot',
          retcode=2,
          data='{ "failure_reason": "FAILURE_SCHEDULE_PUSH_ERROR" }',
      ),
      api.post_check(
          post_process.StepFailure,
          'Run Qualbot.call chromite.api.QualbotService/RunQualbot',
      ),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'service-endpoint-failure-no-response',
      api.build_menu.set_build_api_return(
          'Run Qualbot',
          'QualbotService/RunQualbot',
          retcode=1,
      ),
      api.post_check(
          post_process.StepFailure,
          'Run Qualbot.call chromite.api.QualbotService/RunQualbot',
      ),
      status='FAILURE',
  )
