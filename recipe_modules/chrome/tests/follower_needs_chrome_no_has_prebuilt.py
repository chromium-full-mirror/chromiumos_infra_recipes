# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.chromiumos.common import PackageInfo

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'chrome',
    'cros_build_api',
]



def RunSteps(api):
  chroot = Chroot()
  build_target = BuildTarget()
  packages = [
      PackageInfo(package_name='chrome-icu', category='chromeos-base',
                  version='1.01')
  ]

  # While chromeos-base/chrome-icu is a follower that needs chrome,
  # since chromite.api.PackageService/HasPrebuilt is not implemented by build
  # API (per the MethodService override below) we assume we are in the window
  # before follower packages existed and return false.
  api.assertions.assertFalse(
      api.chrome.follower_lacks_prebuilt(build_target, chroot, packages))


def GenTests(api):
  yield api.test(
      'basic',
      api.cros_build_api.remove_endpoints(['PackageService/HasPrebuilt']),
  )
