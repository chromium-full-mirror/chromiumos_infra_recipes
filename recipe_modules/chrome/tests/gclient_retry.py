# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'chrome',
]



def RunSteps(api):
  chroot = Chroot()
  build_target = BuildTarget()

  api.assertions.assertEqual(api.chrome.gclient_sync_timeout_seconds, 1)

  with api.step.nest('checkout passes retry'):
    api.chrome.sync(
        chrome_root=api.path.start_dir / 'chrome', chroot=chroot,
        build_target=build_target, internal=False,
        cache_dir=api.path.start_dir.joinpath('chrome').joinpath('cache'))

  with api.step.nest('checkout fails retry'):
    api.assertions.assertRaises(
        api.step.InfraFailure, api.chrome.sync,
        chrome_root=api.path.start_dir / 'chrome', chroot=chroot,
        build_target=build_target, internal=True,
        cache_dir=api.path.start_dir.joinpath('chrome').joinpath('cache'))


def GenTests(api):

  def attempt_gclient_sync(api, attempt, step_name, retcode=0):
    step_text = step_name + '.sync chrome.gclient sync'
    if attempt > 1:
      step_text += ' (' + str(attempt) + ')'
    return api.step_data(step_text, retcode=retcode)

  yield api.test(
      'basic',
      attempt_gclient_sync(api, 1, 'checkout passes retry'),
      attempt_gclient_sync(api, 1, 'checkout fails retry', retcode=1),
      attempt_gclient_sync(api, 2, 'checkout fails retry', retcode=1),
      api.properties(**{
          '$chromeos/chrome': ChromeProperties(gclient_sync_timeout_seconds=1)
      }),
  )
