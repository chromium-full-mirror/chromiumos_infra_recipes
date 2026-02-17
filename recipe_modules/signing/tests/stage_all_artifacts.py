# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for stage_all_artifacts."""

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.common import (CHANNEL_CANARY)
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
    'signing',
]


def RunSteps(api: RecipeApi):
  channels = [CHANNEL_CANARY]
  api.signing.stage_all_artifacts(
      channels=channels,
  )


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
          post_process.MustRun,
          'upload unsigned artifacts to chromeos-releases bucket',
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='SUCCESS')
