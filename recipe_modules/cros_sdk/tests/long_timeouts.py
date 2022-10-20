# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.assertions.assertFalse(api.cros_sdk.long_timeouts)
  api.cros_sdk.long_timeouts = False
  api.assertions.assertFalse(api.cros_sdk.long_timeouts)
  api.cros_sdk.long_timeouts = True
  api.assertions.assertTrue(api.cros_sdk.long_timeouts)
  api.cros_sdk.long_timeouts = False
  api.assertions.assertTrue(api.cros_sdk.long_timeouts)


def GenTests(api):
  yield api.test('basic')
