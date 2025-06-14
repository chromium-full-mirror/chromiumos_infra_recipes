# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for sign_artifacts."""

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.common import (CHANNEL_CANARY, IMAGE_TYPE_BASE)
from PB.chromiumos.signing import BuildTargetSigningConfig
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'signing',
]


def RunSteps(api: RecipeApi):
  # For coverage, set to the default value.
  api.signing.test_api.signing_config_test_data = '''build_target_signing_configs {
  build_target: "kukui"
}'''
  # Fetch config.
  config = api.signing.get_config()
  expected_config = BuildTargetSigningConfig(build_target='kukui')
  api.assertions.assertEqual(config, expected_config)

  sign_types = [IMAGE_TYPE_BASE]
  channels = [CHANNEL_CANARY]

  processed_config, _ = api.signing.setup_signing(sign_types, channels)
  api.assertions.assertEqual(None, processed_config)

  # Call signing.
  api.signing.sign_artifacts(
      sign_types=sign_types, channels=channels,
      local_artifact_dir=api.path.start_dir / 'shellball-dir')


def GenTests(api: RecipeTestApi):

  yield api.build_menu.test(
      'basic',
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(local_signing=True,
                                        gs_upload_bucket='chromeos-releases'))
          }),
      api.post_check(
          post_process.StepTextEquals,
          'sign artifacts',
          'Skipping signing for this board due to empty signing config. See go/cros-signing-help for onboarding instructions.',
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='SUCCESS')
