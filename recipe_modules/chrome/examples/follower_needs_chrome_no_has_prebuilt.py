# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'chrome',
]

from PB.chromiumos.common import Chroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo

from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

def RunSteps(api):
  chroot = Chroot()
  build_target = BuildTarget()
  packages = [PackageInfo(package_name='chrome-icu',
                          category='chromeos-base',
                          version='1.01')]

  # While chromeos-base/chrome-icu is a follower that needs chrome,
  # since chromite.api.PackageService/HasPrebuilt is not implemented by build
  # API (per the MethodService override below) we assume we are in the window
  # before follower packages existed and return false.
  api.assertions.assertFalse(api.chrome.follower_lacks_prebuilt(
      build_target, chroot, packages))


def GenTests(api):
  content = '{"methods": [{"method": "chromite.api.PackageService/Other"}]}'

  yield api.test(
      'basic',
      api.step_data('call chromite.api.MethodService/Get.read output file',
                    api.file.read_raw(content=content)),
  )
