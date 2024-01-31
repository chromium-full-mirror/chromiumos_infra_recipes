# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]



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
