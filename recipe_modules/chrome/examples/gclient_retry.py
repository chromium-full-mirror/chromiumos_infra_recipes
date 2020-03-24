# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/step',
    'chrome',
]

from PB.chromiumos.common import Chroot
from PB.chromiumos.common import BuildTarget

from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties


def RunSteps(api):
  chroot = Chroot()
  build_target = BuildTarget()
  with api.step.nest('internal checkout passes retry') as test_step:
    api.chrome.sync(
        chrome_root=api.path['start_dir'].join('chrome'),
        chroot=chroot,
        build_target=build_target,
        internal=True,
    )
  with api.step.nest('external checkout passes retry') as test_step:
    api.chrome.sync(
        chrome_root=api.path['start_dir'].join('chrome'),
        chroot=chroot,
        build_target=build_target,
        internal=True,
    )
  with api.step.nest('internal checkout fails retry') as test_step:
    api.assertions.assertRaises(
        api.step.InfraFailure, api.chrome.sync,
        chrome_root=api.path['start_dir'].join('chrome'), chroot=chroot,
        build_target=build_target, internal=True)

  with api.step.nest('external checkout fails retry') as test_step:
    api.assertions.assertRaises(
        api.step.InfraFailure, api.chrome.sync,
        chrome_root=api.path['start_dir'].join('chrome'), chroot=chroot,
        build_target=build_target, internal=False)


def GenTests(api):

  def attempt_gclient_sync(api, attempt, step_name):
    step_text = step_name + '.sync chrome.gclient sync'
    if attempt > 1:
      step_text += ' (' + str(attempt) + ')'
    return api.step_data(
        step_text, times_out_after=api.chrome.gclient_sync_timeout_seconds + 1)

  yield (api.test('basic') +  #
         attempt_gclient_sync(api, 1, 'internal checkout fails retry') +  #
         attempt_gclient_sync(api, 2, 'internal checkout fails retry') +  #
         attempt_gclient_sync(api, 1, 'external checkout fails retry') +  #
         attempt_gclient_sync(api, 2, 'external checkout fails retry') +  #
         attempt_gclient_sync(api, 1, 'internal checkout passes retry') +  #
         attempt_gclient_sync(api, 1, 'external checkout passes retry'))
