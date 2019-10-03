# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'chrome',
]

from PB.chromiumos.common import Chroot
from PB.chromiumos.common import BuildTarget

from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

def RunSteps(api):
  chroot = Chroot()
  build_target = BuildTarget()
  api.chrome.sync(
      chrome_root=api.path['start_dir'].join('chrome'),
      chroot=chroot,
      build_target=build_target,
      internal=True,
  )
  api.chrome.sync(
      chrome_root=api.path['start_dir'].join('chrome'),
      chroot=chroot,
      build_target=build_target,
      internal=False,
  )

  api.chrome.build_chrome_from_source(build_target, chroot)


def GenTests(api):
  yield (api.test('basic'))

  yield (api.test('with_properties') + #
         api.properties(**{
             "$chromeos/chrome":
             ChromeProperties(parallel_sync_jobs=42)
         }))

  yield (api.test('no-build-chrome') + #
         api.step_data(
             'call chromite.api.PackageService/BuildsChrome.read output file',
             api.file.read_raw(content='{"builds_chrome": false}')))
