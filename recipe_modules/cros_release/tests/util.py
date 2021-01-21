# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_release',
]

from PB.chromiumos.common import (CHANNEL_UNSPECIFIED, CHANNEL_DEV,
                                  CHANNEL_STABLE, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_TEST_GUEST_VM, IMAGE_TYPE_FIRMWARE)


def RunSteps(api):
  api.cros_release.massage_channels([CHANNEL_STABLE, CHANNEL_DEV])
  api.cros_release._validate_sign_types([IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE])

  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_release.massage_channels([CHANNEL_UNSPECIFIED])
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_release._validate_sign_types([IMAGE_TYPE_TEST_GUEST_VM])


def GenTests(api):
  yield api.test('basic')
