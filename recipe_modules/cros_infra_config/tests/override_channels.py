# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
]



def RunSteps(api):
  api.assertions.assertTrue(
      api.cros_infra_config.should_override_release_channels)
  api.assertions.assertEqual(['2', '3'],
                             api.cros_infra_config.override_release_channels)


def GenTests(api):
  yield api.test(
      'override-channels',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      should_override_release_channels=True,
                      override_release_channels=['2', '3'])
          }),
      api.post_process(post_process.DropExpectation),
  )
