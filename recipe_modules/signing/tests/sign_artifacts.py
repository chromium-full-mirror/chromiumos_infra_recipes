# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for sign_artifacts."""

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.signing import BuildTargetSigningConfig, BuildTargetSigningConfigs, SigningConfig
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
  expected_config = BuildTargetSigningConfigs(
      build_target_signing_configs=[
          BuildTargetSigningConfig(
              build_target='eve',
              signing_configs=[
                  SigningConfig(
                      keyset='eve-foo-bar',
                      ensure_no_password=True,
                      firmware_update=True,
                  ),
              ],
          ),
      ],
  )
  api.assertions.assertEqual(config, expected_config)
  # Call signing.
  api.signing.sign_artifacts()


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'basic',
      api.properties(**{
          '$chromeos/signing':
              MessageToDict(SigningProperties(local_signing=True))
      }), api.post_process(post_process.DropExpectation),
      builder='eve-release-main')

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
      builder='eve-release-main')
