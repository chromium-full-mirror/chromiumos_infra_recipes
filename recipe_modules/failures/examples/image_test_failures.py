# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]

from PB.chromite.api.image import Image
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import IMAGE_TYPE_TEST


def RunSteps(api):
  api.failures.raise_failed_image_tests([])
  api.assertions.assertRaises(
      api.step.StepFailure, api.failures.raise_failed_image_tests, [
          Image(path='path', type=IMAGE_TYPE_TEST,
                build_target=BuildTarget(name='build_target'))
      ])


def GenTests(api):
  yield api.test('basic')
