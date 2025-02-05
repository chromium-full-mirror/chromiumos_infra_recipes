# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify methods for shellball versions."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.chromiumos import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'signing',
]


def RunSteps(api: RecipeApi):
  channels = [common_pb2.Channel.CHANNEL_DEV, common_pb2.Channel.CHANNEL_CANARY]
  shellball_versions = api.signing.get_shellball_versions(channels)
  expected_versions = {
      'dev-channel': '4.0',
      'canary-channel': '1.0',
  }
  api.assertions.assertEqual(expected_versions, shellball_versions)
  api.signing.upload_shellball_latest_file(shellball_versions['canary-channel'])
  api.signing.upload_shellball_latest_file(shellball_versions['dev-channel'])


def GenTests(api: RecipeTestApi):
  yield api.test(
      'shellball-versions',
      api.step_data(
          'get latest shellball version by channel.gsutil reading LATEST-SHELLBALL version for dev-channel',
          stdout=api.raw_io.output('3.0')),
      api.step_data(
          'get latest shellball version by channel.gsutil reading LATEST-SHELLBALL version for canary-channel',
          retcode=1),
      api.post_check(
          post_process.MustRun,
          'get latest shellball version by channel.gsutil reading LATEST-SHELLBALL version for dev-channel'
      ),
      api.post_check(
          post_process.MustRun,
          'get latest shellball version by channel.gsutil reading LATEST-SHELLBALL version for canary-channel'
      ),
      api.post_check(post_process.MustRun, 'gsutil upload LATEST-SHELLBALL'),
      api.post_check(post_process.MustRun,
                     'gsutil upload LATEST-SHELLBALL (2)'),
      api.post_process(post_process.DropExpectation),
  )
