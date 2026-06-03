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
    'recipe_engine/context',
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
  protoc_path = api.path.dirname(
      api.cipd.ensure_tool('infra/3pp/tools/protoc/${platform}',
                           "version:3@32.1", executable_path="bin/protoc"))
  with api.context(env_prefixes={'PATH': [protoc_path]}):
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
    for launched_test in response.launched_tests:
      link_name = ""
      if launched_test.test_effort_id:
        link_name += f"{launched_test.test_effort_id}:"
      if launched_test.test_effort_name:
        link_name += launched_test.test_effort_name
      if link_name and launched_test.test_url:
        presentation.links[link_name] = launched_test.test_url
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

  def check_link(check, steps, link_name, expected_link):
    check(steps['Run Qualbot'].links[link_name] == expected_link)

  yield api.build_menu.test(
      'success-with-response',
      api.build_menu.set_build_api_return(
          'Run Qualbot',
          'QualbotService/RunQualbot',
          retcode=0,
          data='''{
          "launched_tests": [
          {
          "test_effort_id": "4388",
          "test_effort_name": "fatcat-ruby-AP-16650.58.0-EC-16667.2.46-RO/RW",
          "test_url": "https://android-build.corp.google.com/abtd/run/L81200030126644839",
          "location": "LOCATION_INTERNAL"
          }
          ]}''',
      ),
      api.post_check(
          check_link, '4388:fatcat-ruby-AP-16650.58.0-EC-16667.2.46-RO/RW',
          'https://android-build.corp.google.com/abtd/run/L81200030126644839'),
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
