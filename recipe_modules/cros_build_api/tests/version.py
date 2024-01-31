# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from RECIPE_MODULES.chromeos.cros_build_api import api as cros_build_api

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]



def RunSteps(api):
  # Verify that the version defaults to 1.1.0.
  api.assertions.assertEqual(str(api.cros_build_api.version), '1.1.0')

  def vers(*args):
    return cros_build_api.Version(*args)

  api.assertions.assertGreater(api.cros_build_api.version, vers(1, 0, 0))
  api.assertions.assertEqual(api.cros_build_api.version, vers(1, 1, 0))
  api.assertions.assertLess(api.cros_build_api.version, vers(1, 1, 1))
  api.assertions.assertLess(api.cros_build_api.version, vers(2, 0, 0))

  api.assertions.assertEqual(
      cros_build_api.Version.ParseVersion('1.2.3'), vers(1, 2, 3))

  # Verfiy that we can set the version for testing.
  api.cros_build_api.GetVersion(test_data='{"version": {"major": 1}}')
  api.assertions.assertEqual(api.cros_build_api.version, vers(1, 0, 0))

  # Verify that we format the response correctly.
  version_string = '4.5.6'
  version = cros_build_api.Version.ParseVersion(version_string)
  api.assertions.assertEqual(
      api.cros_build_api.GetVersion(test_data=version.FormatResponse()),
      version)


def GenTests(api):
  yield api.test('basic', api.cros_build_api.call_version_service(True))
