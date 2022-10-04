# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.common import IMAGE_TYPE_BASE
from PB.chromiumos.common import IMAGE_TYPE_TEST_GUEST_VM
from PB.chromiumos.common import IMAGE_TYPE_FIRMWARE

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_release',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_release.validate_sign_types([IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE])
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_release.validate_sign_types([IMAGE_TYPE_TEST_GUEST_VM])


def GenTests(api):
  yield api.test('basic')
