# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_infra_config',
]



def RunSteps(api):
  api.assertions.assertTrue(
      'chromeos.cros_infra_config.image_builder_parallelization' in
      api.cros_infra_config.experiments)


def GenTests(api):

  yield api.test(
      'experiments',
      api.buildbucket.generic_build(experiments=[
          'chromeos.cros_infra_config.image_builder_parallelization'
      ]), api.post_process(DropExpectation))
