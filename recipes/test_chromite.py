# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests chromite.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_cost',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]

from PB.chromite.api.test import ChromitePytestRequest, ChromiteUnitTestRequest


def RunSteps(api):
  with api.build_menu.configure_builder(None) as config:
    if config:
      api.build_menu.setup_workspace_and_chroot()
      api.cros_build_api.TestService.ChromitePytest(
          ChromitePytestRequest(chroot=api.cros_sdk.chroot),
          name='run chromite pytest')
      api.cros_build_api.TestService.ChromiteUnitTest(
          ChromiteUnitTestRequest(chroot=api.cros_sdk.chroot),
          name='run chromite unit tests')


def GenTests(api):
  yield api.test('no-gerrit-changes', api.test_util.test_build().build)

  yield api.test('one-gerrit-change',
                 api.test_util.test_build(cq=True, builder='chromite-cq').build)

  yield api.test('builder-no-longer-exists',
                 api.test_util.test_build(builder='none').build)
