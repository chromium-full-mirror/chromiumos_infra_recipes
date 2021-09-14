# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests chromite.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]

from PB.chromite.api.test import ChromitePytestRequest, ChromiteUnitTestRequest


def RunSteps(api):
  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot():
    api.cros_build_api.TestService.ChromitePytest(
        ChromitePytestRequest(chroot=api.cros_sdk.chroot),
        name='run chromite pytest')
    api.cros_build_api.TestService.ChromiteUnitTest(
        ChromiteUnitTestRequest(chroot=api.cros_sdk.chroot),
        name='run chromite unit tests')


def GenTests(api):

  def test(name, **kwargs):
    return api.test(name, api.test_util.test_child_build(None, **kwargs).build)

  yield test('no-gerrit-changes', cq=True, builder='chromite-cq')

  yield test('postsubmit', builder='chromite-postsubmit')

  yield test('one-gerrit-change', cq=True, builder='chromite-cq')

  yield test('builder-no-longer-exists', builder='none')
