# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/properties',
    'phosphorus',
]



def RunSteps(api):
  api.phosphorus.build_parallels_image_provision(
      'gs://chromeos-image-archive/eve-release/R86-13380.0.0')
  api.phosphorus.build_parallels_image_provision(
      'gs://chromeos-image-archive/eve-release/R86-13381.0.0')

  api.phosphorus.build_parallels_image_save('needs_repair')


def GenTests(api):
  yield api.test('basic', api.phosphorus.properties(dut_name='my-dut-name'))

  yield api.test(
      'provision-fail',
      api.phosphorus.properties(dut_name='my-dut-name'),
      api.override_step_data(
          'call `phosphorus`.build-parallels-image-provision', retcode=2),
      status='INFRA_FAILURE',
  )
