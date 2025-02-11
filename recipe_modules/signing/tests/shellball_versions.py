# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify methods for shellball versions."""

from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'signing',
]

PROPERTIES = {
    'expected_version':
        Property(
            help='Expected shellball version returned in test.',
            kind=str,
        )
}


def RunSteps(api: RecipeApi, expected_version: str):
  shellball_version = api.signing.get_shellball_version()
  api.assertions.assertEqual(expected_version, shellball_version)
  api.signing.upload_shellball_latest_file(shellball_version)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'increment-shellball-version',
      api.properties(
          expected_version='4.0', **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'shellball-target',
                  },
              },
          }),
      api.step_data(
          'get latest shellball version for shellball-target.gsutil reading LATEST-SHELLBALL version',
          stdout=api.raw_io.output('3.0')),
      api.post_check(post_process.MustRun, 'gsutil upload LATEST-SHELLBALL'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'start-new-shellball-version',
      api.properties(
          expected_version='1.0', **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'shellball-target',
                  },
              },
          }),
      api.step_data(
          'get latest shellball version for shellball-target.gsutil reading LATEST-SHELLBALL version',
          retcode=1),
      api.post_check(post_process.MustRun, 'gsutil upload LATEST-SHELLBALL'),
      api.post_process(post_process.DropExpectation),
  )
