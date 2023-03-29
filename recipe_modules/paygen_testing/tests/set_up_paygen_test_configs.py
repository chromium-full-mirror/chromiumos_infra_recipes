# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify paygen_testing.set_up_paygen_test_configs."""
import PB.chromiumos.common as common_pb2
from PB.recipe_modules.chromeos.paygen_testing.tests.set_up_paygen_test import AutoupdateTestConfig
from PB.recipe_modules.chromeos.paygen_testing.tests.set_up_paygen_test import SetUpPaygenTestRequest
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_storage',
    'gitiles',
    'paygen_testing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = SetUpPaygenTestRequest


class dotdict(dict):
  """dot.notation access to dictionary attributes.

  This is necessary because of the way the recipes engine handles request
  objects, and ensuring our test is able to replicate the code under test.
  """
  __getattr__ = dict.get
  __setattr__ = dict.__setitem__
  __delattr__ = dict.__delitem__


def RunSteps(api: RecipeApi, properties: SetUpPaygenTestRequest):
  api.paygen_testing.set_up_paygen_test_configs(properties, [
      dotdict(
          dict(
              local_path='/path/path.json', remote_uri=(
                  'gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
                  'chromeos_12345.0.0_zork_canary-channel_full_test.bin-abc')))
  ])


def GenTests(api: RecipeTestApi):

  yield api.test(
      'dryrun',
      api.properties(
          SetUpPaygenTestRequest(
              generation_request=api.paygen_testing
              .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          )),
      api.post_check(post_process.StepTextEquals,
                     'setting up paygen test config', 'dry run, skip testing'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'missing-au-test-config',
      api.properties(
          SetUpPaygenTestRequest(generation_request=api.paygen_testing
                                 .EXAMPLE_GEN_REQUEST_DELTA_DLC[0])),
      api.post_check(post_process.StepTextEquals,
                     'setting up paygen test config',
                     'no test configured, skip testing'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'signed-image',
      api.properties(
          SetUpPaygenTestRequest(
              generation_request=api.paygen_testing
              .EXAMPLE_GEN_REQUESTS_DELTA_SIGNED[0], autoupdate_test_configs=[
                  AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                       applicable_models=['woomax'])
              ])),
      api.post_check(post_process.StepFailure, 'setting up paygen test config'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'full-run',
      api.gitiles.get_file(
          api.paygen_testing.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.properties(
          SetUpPaygenTestRequest(
              generation_request=api.paygen_testing
              .EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED_NO_DRYRUN[0],
              autoupdate_test_configs=[
                  AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                       applicable_models=['woomax'],
                                       src_channel='canary-channel',
                                       src_version='12345.0.0')
              ])),
      api.cros_storage.test_listing(
          'setting up paygen test config.discover gs artifacts.gsutil list',
          ('gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
           'chromeos_12345.0.0_zork_canary-channel_full_test.bin-abc'),
      ),
      api.post_process(post_process.DropExpectation),
  )
