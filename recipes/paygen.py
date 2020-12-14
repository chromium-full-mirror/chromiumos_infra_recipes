# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS payloads (AU deltas etc)."""

import json

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
    'cros_paygen',
    'cros_sdk',
    'cros_source',
    'cros_storage',
    'workspace_util',
]

from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process

from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen import PaygenProperties
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties

PROPERTIES = PaygenProperties


def RunSteps(api, properties):
  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    with api.step.nest('initialization'):

      # Sync chromite only.
      api.cros_source.ensure_synced_cache(projects=['chromiumos/chromite'])

      # Create chroot.
      api.cros_sdk.create_chroot(version=None, use_image=False,
                                 timeout_sec=None)

    with api.step.nest('doing paygen'):
      # Execute build api endpoint for paygen.
      response = api.cros_build_api.PayloadService.GeneratePayload(
          properties.request, name='making single payload')

    with api.step.nest('testing paygen') as presentation:
      if properties.request.dryrun:
        presentation.step_text = 'dry run, skip testing'
        return
      if not properties.autoupdate_test_configs:
        presentation.step_text = 'no test configured, skip testing'
        return
      if properties.request.WhichOneof(
          'tgt_image_oneof') != 'tgt_unsigned_image':
        raise StepFailure(
            'autoupdate tests can only be run on payloads with unsigned images')

      milestone = properties.request.tgt_unsigned_image.milestone
      tgt_payload = (
          api.cros_storage.FullPayload.parse_uri(response.remote_uri, milestone)
          or api.cros_storage.DeltaPayload.parse_uri(response.remote_uri,
                                                     milestone))
      paygen_test_configs = []
      for test_config in properties.autoupdate_test_configs:
        paygen_test_configs.append(
            api.cros_paygen.create_paygen_test_config(
                tgt_payload, src_version=test_config.src_version,
                src_channel=test_config.src_channel,
                delta_type=test_config.delta_type,
                applicable_models=test_config.applicable_models))
      api.cros_paygen.schedule_au_tests(paygen_test_configs)


# TODO(crbug.com/1157719): Improve testing mock data. There is a disconnect
# between the mock data and the Recipe logic. For example, a call to
# GeneratePayloads with no request still returns a successful response.
def GenTests(api):

  def generate_payload_response(api, is_success=True, local_path='',
                                remote_uri=''):
    data = json.dumps(
        dict(success=is_success, local_path=local_path, remote_uri=remote_uri))
    return api.cros_build_api.set_api_return(parent_step_name='doing paygen',
                                             step_name='making single payload',
                                             data=data,
                                             retcode=0 if is_success else 1)

  full_payload_uri = (
      'gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
      'chromeos_12345.0.0_zork_canary-channel_full_test.bin-abc')

  delta_payload_uri = (
      'gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
      'chromeos_12345.0.0-12345.0.0_zork_canary-channel_delta_test.bin-abc')

  yield api.test(
      'dryrun',
      api.properties(
          PaygenProperties(
              request=api.cros_paygen.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              autoupdate_test_configs=[
                  AutoupdateTestConfig(
                      delta_type=PaygenOrchestratorProperties.OMAHA,
                      applicable_models=['woomax'])
              ])),
      generate_payload_response(api),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'no-testing',
      api.properties(
          PaygenProperties(
              request=api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_N2N[0])),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'with-testing',
      api.properties(
          PaygenProperties(
              request=api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_N2N[0],
              autoupdate_test_configs=[
                  AutoupdateTestConfig(
                      src_version='123', src_channel='canary-channel',
                      delta_type=PaygenOrchestratorProperties.OMAHA,
                      applicable_models=['woomax']),
                  AutoupdateTestConfig(
                      src_version='123', src_channel='canary-channel',
                      delta_type=PaygenOrchestratorProperties.OMAHA,
                      applicable_models=['other']),
              ])),
      api.cros_storage.test_listing(
          'testing paygen.discover gs artifacts.gsutil list',
          full_payload_uri,
      ),
      api.cros_storage.test_listing(
          'testing paygen.discover gs artifacts (2).gsutil list',
          full_payload_uri,
      ),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'mismatched-payload-and-testing-config',
      api.properties(
          PaygenProperties(
              request=api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_N2N[0],
              autoupdate_test_configs=[
                  AutoupdateTestConfig(
                      delta_type=PaygenOrchestratorProperties.OMAHA,
                      applicable_models=['woomax'])
              ])),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'mistmatch-non-test-payload-with-testing-config',
      api.properties(
          PaygenProperties(
              request=api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
              autoupdate_test_configs=[
                  AutoupdateTestConfig(
                      delta_type=PaygenOrchestratorProperties.OMAHA,
                      applicable_models=['woomax'])
              ])),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )
