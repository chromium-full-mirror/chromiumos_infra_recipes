# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api import sysroot
from PB.chromiumos import common as chromiumos

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  # Existing path produces expected dictionary
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

  failed_packages = api.cros_build_api.failed_pkg_logs(
      sysroot.InstallToolchainRequest(),
      sysroot.InstallPackagesResponse(failed_package_data=packages), lambda *
      args: 'log file content goes here')

  api.assertions.assertTrue(len(failed_packages) == len(packages))
  for i, pkg in enumerate(packages):
    api.assertions.assertTrue(failed_packages[i][0] == pkg.name)

  # Nonexistent path does not produce dictionary
  packages = [
      sysroot.FailedPackageData(
          name=chromiumos.PackageInfo(category='foo',
                                      package_name='bar%d' % num,
                                      version='%d' % num),
          log_path=chromiumos.Path(
              path='',
              location=chromiumos.Path.Location.INSIDE,
          )) for num in range(60)
  ]

  failed_packages = api.cros_build_api.failed_pkg_logs(
      sysroot.InstallToolchainRequest(),
      sysroot.InstallPackagesResponse(failed_package_data=packages), lambda *
      args: 'log file content goes here')

  api.assertions.assertTrue(len(failed_packages) == len(packages))
  for i, pkg in enumerate(packages):
    api.assertions.assertTrue(failed_packages[i][0] == pkg.name)
    api.assertions.assertTrue(failed_packages[i][1] == '')


def GenTests(api):
  yield api.test('basic')
