# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for sign_artifacts."""

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.common import (CHANNEL_CANARY, CHANNEL_DEV, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_FACTORY)
from PB.chromiumos.signing import BuildTargetSigningConfig, SigningConfig
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  # Fetch config.
  config = api.signing.get_config()
  expected_config = BuildTargetSigningConfig(
      build_target='kukui',
      signing_configs=[
          SigningConfig(
              image_type=IMAGE_TYPE_BASE,
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_FACTORY,
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
          ),
      ],
  )
  api.assertions.assertEqual(config, expected_config)

  sign_types = [IMAGE_TYPE_BASE]
  channels = [CHANNEL_CANARY, CHANNEL_DEV]

  processed_config, _ = api.signing.setup_signing(sign_types, channels)
  expected_processed_config = BuildTargetSigningConfig(
      build_target='kukui',
      signing_configs=[
          SigningConfig(
              image_type=IMAGE_TYPE_BASE,
              channel=CHANNEL_CANARY,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='chromiumos_base_image.tar.xz',
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_BASE,
              channel=CHANNEL_DEV,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='chromiumos_base_image.tar.xz',
          ),
      ],
  )
  api.assertions.assertEqual(processed_config, expected_processed_config)

  # Call signing.
  api.signing.sign_artifacts(sign_types, channels)


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
      api.post_check(post_process.MustRun,
                     'sign artifacts.call chromite.api.ImageService/SignImage'),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.gsutil rsync'
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main')

  yield api.build_menu.test(
      'no-signing-config',
      api.properties(**{
          '$chromeos/signing':
              MessageToDict(SigningProperties(local_signing=True))
      }), api.post_process(post_process.DropExpectation), build_target='eve',
      builder='eve-release-main', status='FAILURE')

  yield api.test(
      'no-builder-config',
      api.post_check(post_process.StepFailure, 'fetch signing config'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'signing-disabled',
      api.post_check(
          post_process.SummaryMarkdown,
          'Cannot sign artifacts when local signing is not configured'),
      api.post_process(post_process.DropExpectation), status='FAILURE',
      build_target='kukui', builder='kukui-release-main')
