# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]

from PB.chromite.api import sysroot
from PB.chromiumos import common as chromiumos


def RunSteps(api):
  packages = [
      sysroot.FailedPackageData(
          name=chromiumos.PackageInfo(category='foo',
                                      package_name='bar%d' % num,
                                      version='%d' % num),
          log_path=chromiumos.Path(
              path='/all/your/oopsie/are/belong/to/us/%d' % num,
              location=chromiumos.Path.Location.INSIDE,
          )) for num in range(60)
  ]
  # Test failed_pkg_names
  # We only care that the function gets used.
  input_proto = sysroot.InstallToolchainRequest()
  api.cros_build_api.SysrootService.InstallToolchain(
      input_proto, pkg_logs_lambda=api.cros_build_api.failed_pkg_logs)

  failed_packages = api.cros_build_api.failed_pkg_logs(
      input_proto,
      sysroot.InstallPackagesResponse(failed_package_data=packages), lambda *
      args: 'log file content goes here')

  api.assertions.assertTrue(len(failed_packages) == len(packages))
  for i, pkg in enumerate(packages):
    api.assertions.assertTrue(failed_packages[i][0] == pkg.name)


def GenTests(api):
  yield api.test('basic')
