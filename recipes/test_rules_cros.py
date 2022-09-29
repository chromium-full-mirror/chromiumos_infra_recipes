# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that runs bazel rules_cros unit tests.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from PB.chromite.api.test import RulesCrosUnitTestRequest

DEPS = [
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot():
    request = RulesCrosUnitTestRequest(chroot=api.cros_sdk.chroot)
    api.cros_build_api.TestService.RulesCrosUnitTest(
        request, name='run rules_cros tests')


def GenTests(api):

  def test(name, **kwargs):
    return api.test(name, api.test_util.test_child_build(None, **kwargs).build)

  yield test('cq', cq=True, builder='rules-cros-cq')

  yield test('builder-no-longer-exists', builder='none')
