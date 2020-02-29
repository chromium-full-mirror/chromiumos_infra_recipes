# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'chrome',
    'gerrit',
]

from copy import deepcopy

from PB.chromiumos.common import Chroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo

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

  ps_info = {
      'host': 'test',
      'info': {'project': 'chromiumos/overlays/chromiumos-overlay',},
      'revision_info': { 'files': {
          'chromeos-base/chromeos-chrome/'
          'chromeos-chrome-81.0.4036.0_rc-r1.ebuild': {},
          'some/path/that/isnt/important': {},
          },
      },
    'patch_set': '3',}
  ps1 = api.gerrit.PatchSet(ps_info)

  ps_info2 = deepcopy(ps_info)
  ps_info2['revision_info']['files'] = {'some/path/that/isnt/important': {},}
  ps2 = api.gerrit.PatchSet(ps_info2)

  api.assertions.assertTrue(
      api.chrome.diffed_files_requires_rebuild(patch_sets=[ps1]))
  api.assertions.assertFalse(
      api.chrome.diffed_files_requires_rebuild(patch_sets=[ps2]))

  api.chrome.builds_chrome_from_source(build_target, chroot)
  api.chrome.builds_chrome_from_source(
      build_target, chroot,
      [PackageInfo(package_name='pack', category='cat', version='1.01')])
  api.chrome.builds_chrome_from_source(
      build_target, chroot, ignore_prebuilts=True)


def GenTests(api):
  yield (api.test('basic'))

  yield (api.test('with_properties') + #
         api.properties(**{
             "$chromeos/chrome":
             ChromeProperties(parallel_sync_jobs=42)
         }))

  yield (api.test('with-properties-custom-build') + #
         api.properties(**{
             "$chromeos/chrome":
             ChromeProperties(
                 version='deadbeef',
                 deps_isolate=ChromeProperties.DepsIsolate(
                     isolated_hash='aaa',
                     isolate_server='aaa.com'
                 )),
         }))

  yield (api.test('no-needs-chrome') + #
         api.step_data(
             'call chromite.api.PackageService/BuildsChrome.read output file',
             api.file.read_raw(content='{"builds_chrome": false}')))

  yield (api.test('no-has-prebuilt') + #
         api.step_data(
             'call chromite.api.PackageService/HasChromePrebuilt'
             '.read output file',
             api.file.read_raw(content='{"has_prebuilt": false}')))
