# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that runs SDK package unit tests.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'recipe_engine/path',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'failures',
    'test_util',
]

from PB.chromite.api.test import BuildTargetUnitTestRequest
from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot():
    with api.step.nest('run SDK package unit tests') as step:
      response = api.cros_build_api.TestService.BuildTargetUnitTest(
          BuildTargetUnitTestRequest(
              build_target=BuildTarget(name='host'), chroot=api.cros_sdk.chroot,
              package_blocklist=[], packages=[],
              result_path=str(api.path.mkdtemp()),
              flags=BuildTargetUnitTestRequest.Flags(
                  code_coverage=False, empty_sysroot=False,
                  testable_packages_optional=False,
                  filter_only_cros_workon=False)),
          response_lambda=api.cros_build_api.failed_pkg_names)
      api.failures.set_failed_packages(step, response.failed_packages)
    # SDK has been modified, so ensure it is not reused.
    api.cros_sdk.mark_sdk_as_dirty()


def GenTests(api):

  def test(name, **kwargs):
    return api.test(name, api.test_util.test_child_build(None, **kwargs).build)

  yield test('cq', cq=True, builder='host-packages-cq')

  yield test('builder-no-longer-exists', builder='none')
