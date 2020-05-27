# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
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
from PB.recipe_modules.chromeos.chrome.examples.test import TestInputProperties

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  chroot = Chroot()
  build_target = BuildTarget()

  # There isn't a protobuf definition for PatchSet, so we create it here.
  need_ps = api.gerrit.PatchSet(
      dict(
          host='test',
          info=dict(project='chromiumos/overlays/chromiumos-overlay'),
          revision_info=dict(
              files={
                  'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild': {
                  },
                  'some/path/that/isnt/important': {},
              }), patch_set='3'))

  no_need_ps = api.gerrit.PatchSet(
      dict(host='test',
           info=dict(project='chromiumos/overlays/chromiumos-overlay'),
           revision_info=dict(files={
               'some/path/that/isnt/important': {},
           }), patch_set='3'))
  ps_list = [need_ps if properties.changes else no_need_ps]

  needs_chrome = api.chrome.needs_chrome(build_target=build_target,
                                         chroot=chroot,
                                         packages=properties.packages)
  api.assertions.assertEqual(properties.needs_chrome, needs_chrome)
  if needs_chrome:
    no_prebuilt = not api.chrome.has_chrome_prebuilt(
        build_target=build_target, chroot=chroot,
        ignore_prebuilts=properties.ignore_prebuilts)

    local_uprev = api.chrome.maybe_uprev_local_chrome(build_target, chroot,
                                                      ps_list)

    follower_lacks_prebuilt = api.chrome.follower_lacks_prebuilt(
        build_target=build_target, chroot=chroot, packages=properties.packages)

    source_needed = no_prebuilt or local_uprev or follower_lacks_prebuilt
    api.assertions.assertEqual(source_needed, properties.expected_builds_from)
    if source_needed:
      api.chrome.sync(
          chrome_root=api.path['start_dir'].join('chrome'),
          chroot=chroot,
          build_target=build_target,
          internal=not properties.external,
      )


def GenTests(api):

  def test_props(skips_chrome_prebuilt=False, needs_chrome=True, changes=True,
                 expected_builds_from=True, chrome_prebuilt=True, **kwargs):
    props = TestInputProperties(needs_chrome=needs_chrome, changes=changes,
                                expected_builds_from=expected_builds_from,
                                **kwargs)
    ret = api.step_data(
        'call chromite.api.PackageService/BuildsChrome.read output file',
        api.file.read_raw(content='{"builds_chrome": %s}' %
                          str(needs_chrome).lower()))
    if not props.ignore_prebuilts and not skips_chrome_prebuilt:
      ret += api.step_data(
          'call chromite.api.PackageService/HasChromePrebuilt.read output file',
          api.file.read_raw(content='{"has_prebuilt": %s}' %
                            str(chrome_prebuilt).lower()))
    return ret + api.properties(props)

  yield api.test('basic', test_props())

  yield api.test('no-changes',
                 test_props(changes=False, expected_builds_from=False))

  yield api.test('ignore-prebuilts', test_props(ignore_prebuilts=True))

  yield api.test('external', test_props(external=True))

  yield api.test(
      'with_properties',
      test_props(),
      api.properties(
          **{"$chromeos/chrome": ChromeProperties(parallel_sync_jobs=42)}),
  )

  yield api.test(
      'with-chrome-icu',
      test_props(packages=[
          PackageInfo(package_name='chrome-icu', category='chromeos-base',
                      version='1.01')
      ]),
  )

  yield api.test(
      'with-properties-custom-build',
      test_props(skips_chrome_prebuilt=True),
      api.properties(
          **{
              "$chromeos/chrome":
                  ChromeProperties(
                      version='deadbeef',
                      deps_isolate=ChromeProperties.DepsIsolate(
                          isolated_hash='aaa', isolate_server='aaa.com')),
          }),
  )

  yield api.test(
      'no-needs-chrome',
      test_props(skips_chrome_prebuilt=True, needs_chrome=False,
                 expected_builds_from=False),
  )

  yield api.test(
      'has-no-prebuilt',
      test_props(chrome_prebuilt=False),
  )
