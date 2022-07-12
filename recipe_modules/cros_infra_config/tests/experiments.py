# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


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
