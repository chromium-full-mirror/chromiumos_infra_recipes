# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.image import Image
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import IMAGE_TYPE_TEST

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  api.failures.raise_failed_image_tests([])
  api.assertions.assertRaises(
      api.step.StepFailure, api.failures.raise_failed_image_tests, [
          Image(path='path', type=IMAGE_TYPE_TEST,
                build_target=BuildTarget(name='build_target'))
      ])


def GenTests(api):
  yield api.test('basic')
