# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import sysroot
from PB.chromiumos import common as chromiumos

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]



def RunSteps(api):
  packages = [
      sysroot.FailedPackageData(
          name=chromiumos.PackageInfo(package_name='p%d' % num),
          log_path=chromiumos.Path(
              path='/all/your/package/are/belong/to/us/p%d' % num))
      for num in range(60)
  ]
  # Test failed_pkg_names
  # We only care that the function gets used.
  input_proto = sysroot.InstallToolchainRequest()
  api.cros_build_api.SysrootService.InstallToolchain(
      input_proto, response_lambda=api.cros_build_api.failed_pkg_data_names)

  failed_packages = api.cros_build_api.failed_pkg_data_names(
      sysroot.InstallPackagesResponse(failed_package_data=packages))

  api.assertions.assertTrue('...' in failed_packages)


def GenTests(api):
  yield api.test('basic')
