# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify methods for signing status."""

from google.protobuf.json_format import ParseDict

from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import CHANNEL_CANARY

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'signing_utils',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PASSED = BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED
FAILED = BuildReport.SignedBuildMetadata.SIGNING_STATUS_FAILED


def RunSteps(api: RecipeApi):
  metadata = ParseDict(api.properties.thaw()['metadata'],
                       message=BuildReport.SignedBuildMetadata)
  expected_status = api.properties.thaw()['expected_status']

  status = api.signing_utils.get_signing_status(metadata, local_signing=True)
  api.assertions.assertEqual(expected_status, status)
  if expected_status == PASSED:
    api.assertions.assertTrue(
        api.signing_utils.signing_succeeded(status, local_signing=True))
  else:
    api.assertions.assertFalse(
        api.signing_utils.signing_succeeded(status, local_signing=True))


def GenTests(api: RecipeTestApi):
  pass_metadata = BuildReport.SignedBuildMetadata(
      release_directory='/archive_dir/',
      status=PASSED,
      board='kukui',
      channel=CHANNEL_CANARY,
      keyset='devkeys',
  )

  yield api.test(
      'passed',
      api.properties(metadata=pass_metadata, expected_status=PASSED),
      api.post_process(post_process.DropExpectation),
  )

  fail_metadata = BuildReport.SignedBuildMetadata(
      release_directory='/archive_dir/',
      status=FAILED,
      board='kukui',
      channel=CHANNEL_CANARY,
      keyset='devkeys',
  )

  yield api.test(
      'failed',
      api.properties(metadata=fail_metadata, expected_status=FAILED),
      api.post_process(post_process.DropExpectation),
  )
