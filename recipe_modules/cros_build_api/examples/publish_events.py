# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api import sysroot

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  # InstallPackagesRequest can be published.
  input_proto = sysroot.InstallPackagesRequest(packages=[{
      'package_name': 'a_test_package'
  }])
  output_proto = api.cros_build_api.SysrootService.InstallPackages(input_proto)
  api.assertions.assertEqual(len(output_proto.failed_package_data), 0)


def GenTests(api):
  yield api.test('basic')
