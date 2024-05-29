# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests chromite.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from PB.chromite.api.test import ChromitePytestRequest
from PB.chromite.api.test import ChromiteUnitTestRequest
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]



def RunSteps(api: RecipeApi):
  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot(force_no_chroot_upgrade=True):
    api.cros_build_api.TestService.ChromitePytest(
        ChromitePytestRequest(chroot=api.cros_sdk.chroot),
        name='run chromite pytest')
    api.cros_build_api.TestService.ChromiteUnitTest(
        ChromiteUnitTestRequest(chroot=api.cros_sdk.chroot),
        name='run chromite unit tests')


def GenTests(api: RecipeTestApi):

  def test(name: str, **kwargs) -> TestData:
    status = kwargs.pop('status', 'SUCCESS')
    return api.test(name,
                    api.test_util.test_child_build(None, **kwargs).build,
                    status=status)

  yield test('cq', cq=True, builder='chromite-cq')

  yield test(
      'snapshot',
      builder='chromite-snapshot',
  )

  yield test(
      'builder-no-longer-exists',
      builder='none',
      status='FAILURE',
  )
