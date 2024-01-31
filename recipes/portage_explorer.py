# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Portage Explorer.

Portage Explorer calls the RunSpiders endpoint from the PortageExplorerService
and uploads the output from calling the endpoint to GS.
"""

import json

from google.protobuf import json_format

from PB.chromite.api.portage_explorer import RunSpidersRequest
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'easy',
]



def RunSteps(api: RecipeApi):
  try:
    with api.build_menu.configure_builder(missing_ok=True), \
        api.build_menu.setup_workspace_and_chroot():
      RunSpiders(api)
  except StepFailure as sf:
    with api.step.nest('failure') as presentation:
      presentation.step_text = str(sf)
    raise sf


def RunSpiders(api: RecipeApi):
  """Call the RunSpiders endpoint and upload to GS.

  Call the RunSpiders endpoint from the PortageExplorerService. Store the
  output as a json in a tmp dir and upload to the portage_explorer bucket in
  GS.
  """
  with api.step.nest('Portage Explorer Service') as presentation:
    output = api.cros_build_api.PortageExplorerService.RunSpiders(
        RunSpidersRequest(chroot=api.cros_sdk.chroot))
    messages_path = api.path.mkdtemp(prefix='run_spiders')
    output_path = messages_path.join('output_proto.json')
    output_json = json.dumps(json_format.MessageToDict(output), indent=2)
    api.file.write_text('portage explorer output', output_path, output_json)
    today = api.time.utcnow()
    builder_id = api.buildbucket.build.id
    gs_path = api.path.join(
        today.strftime('%Y/%m/%d/'), builder_id, 'portage_explorer.json')
    api.gsutil.upload(output_path, 'portage_explorer', str(gs_path))
    presentation.logs['response'] = output_json


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'portage-explorer-test',
      api.post_check(
          post_process.MustRun,
          'Portage Explorer Service.call chromite.api.PortageExplorerService/RunSpiders'
      ),
      api.post_check(post_process.MustRun,
                     'Portage Explorer Service.gsutil upload'),
      api.post_check(
          post_process.StepCommandContains,
          'Portage Explorer Service.gsutil upload', [
              'gs://portage_explorer/2012/05/14/8945511751514863184/portage_explorer.json'
          ]))

  yield api.test(
      'configure-failure',
      api.runtime.global_shutdown_on_step(
          'configure builder.cros_infra_config.read builder configs.fetch HEAD:generated/builder_configs.binaryproto'
      ),
      api.post_check(
          post_process.StepTextEquals, 'failure',
          "Infra Failure: Step('configure builder.cros_infra_config.update src_state.gitiles_commit.set gitiles_commit') (canceled) (retcode: None)"
      ),
      # TODO (b/275363240): is this status code wrong?
      status='CANCELED',
  )

  yield api.test(
      'api-endpoint-failure',
      api.build_menu.set_build_api_return('Portage Explorer Service',
                                          'PortageExplorerService/RunSpiders',
                                          retcode=1),
      api.post_check(
          post_process.StepTextEquals, 'failure',
          "Step('Portage Explorer Service.call chromite.api.PortageExplorerService/RunSpiders.call build API script') (retcode: 1)"
      ),
      status='FAILURE',
  )
