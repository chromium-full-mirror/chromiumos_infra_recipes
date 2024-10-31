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
    'signing_utils',
]


def RunSteps(api: RecipeApi):
  channels = [common_pb2.Channel.CHANNEL_DEV, common_pb2.Channel.CHANNEL_CANARY]
  gs_bucket = 'shellball-bucket'
  current_versions = api.signing_utils.get_current_shellball_versions(
      channels, gs_bucket)
  new_versions = api.signing_utils.increment_shellball_major_versions(
      current_versions)
  api.signing_utils.custom_artifact_versions = new_versions

  expected_dirs = {
      common_pb2.Channel.CHANNEL_DEV: 'dev-channel/shellball-target/4.0',
      common_pb2.Channel.CHANNEL_CANARY: 'canary-channel/shellball-target/1.0',
  }

  for channel in channels:
    gs_dir = api.signing_utils.get_gs_dir_for_channel(channel)
    api.assertions.assertEqual(expected_dirs[channel], gs_dir)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'shellball-versions',
      api.properties(**{
          '$chromeos/build_menu': {
              'build_target': {
                  'name': 'shellball-target',
              },
          },
      }),
      api.step_data(
          'get latest shellball version by channel.gsutil reading LATEST-SHELLBALL version for dev-channel',
          stdout=api.raw_io.output('3.0')),
      api.step_data(
          'get latest shellball version by channel.gsutil reading LATEST-SHELLBALL version for canary-channel',
          retcode=1),
      api.post_check(post_process.MustRun,
                     'get latest shellball version by channel'),
      api.post_process(post_process.DropExpectation),
  )
