# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.assertions.assertTrue(
      api.cros_build_api.has_endpoint(api.cros_build_api.PackageService,
                                      'BuildsChrome'))
  api.assertions.assertFalse(
      api.cros_build_api.has_endpoint(api.cros_build_api.PackageService,
                                      'LaunchNukes'))
  api.assertions.assertFalse(
      api.cros_build_api.has_endpoint(api.cros_build_api.__init__,
                                      'BuildsChrome'))


def GenTests(api):
  yield api.test('basic')
