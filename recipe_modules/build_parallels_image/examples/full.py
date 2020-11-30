# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.build_parallels_image.build_parallels_image \
  import BuildParallelsImageEnvProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'build_parallels_image',
]


def RunSteps(api):
  api.build_parallels_image.provision(
      'gs://chromeos-image-archive/eve-release/R86-13380.0.0')
  api.build_parallels_image.provision(
      'gs://chromeos-image-archive/eve-release/R86-13381.0.0')
  name = api.build_parallels_image.dut_name
  assert name == 'my-dut-name'


def GenTests(api):
  yield api.test('basic',
                 api.build_parallels_image.environment(dut_name='my-dut-name'))

  yield api.test(
      'provision-fail',
      api.build_parallels_image.environment(dut_name='my-dut-name'),
      api.override_step_data('call `build-parallels-image`.provision',
                             retcode=2),
      api.post_check(post_process.StatusFailure))

  yield api.test(
      'bad-environment-var',
      api.properties.environ(
          BuildParallelsImageEnvProperties(SWARMING_BOT_ID='bad-val')),
      api.expect_exception('ValueError'))
