# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import sysroot
from PB.chromiumos import common as chromiumos

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  # Existing path produces expected dictionary
  packages = [
      sysroot.FailedPackageData(
          name=chromiumos.PackageInfo(category='foo',
                                      package_name='bar%d' % num,
                                      version='%d' % num),
          # TODO(b/265885353): Remove INSIDE once old branches are dead.
          log_path=chromiumos.Path(
              path='/all/your/oopsie/are/belong/to/us/%d' % num,
              location=location))
      for num in range(60)
      for location in (chromiumos.Path.OUTSIDE, chromiumos.Path.INSIDE)
  ]

  failed_packages = api.cros_build_api.failed_pkg_logs(
      sysroot.InstallToolchainRequest(),
      sysroot.InstallPackagesResponse(failed_package_data=packages))

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
              location=location,
          ))
      for num in range(60)
      for location in (chromiumos.Path.OUTSIDE, chromiumos.Path.INSIDE)
  ]

  failed_packages = api.cros_build_api.failed_pkg_logs(
      sysroot.InstallToolchainRequest(),
      sysroot.InstallPackagesResponse(failed_package_data=packages))

  api.assertions.assertTrue(len(failed_packages) == len(packages))
  for i, pkg in enumerate(packages):
    api.assertions.assertTrue(failed_packages[i][0] == pkg.name)
    api.assertions.assertTrue(failed_packages[i][1] == '')

  # Failure to read file does not throw an exception.
  packages = [
      sysroot.FailedPackageData(
          name=chromiumos.PackageInfo(category='test', package_name='package',
                                      version='1'),
          log_path=chromiumos.Path(
              path='/all/your/oopsie/are/belong/to/us/1',
              location=chromiumos.Path.Location.INSIDE,
          ))
  ]

  failed_packages = api.cros_build_api.failed_pkg_logs(
      sysroot.InstallToolchainRequest(),
      sysroot.InstallPackagesResponse(failed_package_data=packages))

  api.assertions.assertTrue(len(failed_packages) == len(packages))
  for i, pkg in enumerate(packages):
    api.assertions.assertTrue(failed_packages[i][0] == pkg.name)
    api.assertions.assertTrue(failed_packages[i][1] == '')


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('read log for test/package', retcode=1),
  )
