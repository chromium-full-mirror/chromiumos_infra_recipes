# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify methods for shellball versions."""

from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.chromiumos import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'signing_utils',
]

PROPERTIES = {
    'expected_gs_dir':
        Property(
            help='Expected GS dir returned in test.',
            kind=str,
        )
}


def RunSteps(api: RecipeApi, expected_gs_dir: str):
  gs_bucket = 'shellball-bucket'
  current_version = api.signing_utils.get_current_shellball_version(gs_bucket)
  new_version = api.signing_utils.increment_shellball_major_version(
      current_version)
  api.signing_utils.custom_artifact_version = new_version
  gs_dir = api.signing_utils.get_gs_dir_for_channel(common_pb2.CHANNEL_AGNOSTIC)
  api.assertions.assertEqual(expected_gs_dir, gs_dir)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'increment-shellball-version',
      api.properties(
          expected_gs_dir='shellball-target/4.0', **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'shellball-target',
                  },
              },
          }),
      api.step_data(
          'get latest shellball version for shellball-target.gsutil reading LATEST-SHELLBALL version',
          stdout=api.raw_io.output('3.0')),
      api.post_check(post_process.MustRun,
                     'get latest shellball version for shellball-target'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'start-new-shellball-version',
      api.properties(
          expected_gs_dir='shellball-target/1.0', **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'shellball-target',
                  },
              },
          }),
      api.step_data(
          'get latest shellball version for shellball-target.gsutil reading LATEST-SHELLBALL version',
          retcode=1),
      api.post_check(post_process.MustRun,
                     'get latest shellball version for shellball-target'),
      api.post_process(post_process.DropExpectation),
  )
