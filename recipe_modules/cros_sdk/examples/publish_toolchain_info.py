# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'cros_build_api',
    'cros_sdk',
]


_TEST_SDK_VERSION_FILE = '''# The last version of the sdk that we built & tested.
SDK_LATEST_VERSION="2022.06.26.170938"

# How to find the standalone toolchains from the above sdk.
TC_PATH="2022/06/%(target)s-2022.06.26.170938.tar.xz"

# Frozen version of SDK used for bootstrapping.
# If unset, SDK_LATEST_VERSION will be used for bootstrapping.
BOOTSTRAP_FROZEN_VERSION="2022.05.09.125449"
'''


def RunSteps(api):
  toolchain_info = api.cros_sdk.get_toolchain_info('eve')
  api.assertions.assertEqual(
      getattr(toolchain_info, 'sdk_version'), '2022.06.26.170938')
  api.assertions.assertEqual(
      getattr(toolchain_info, 'toolchain_url'),
      '2022/06/%(target)s-2022.06.26.170938.tar.xz')
  api.assertions.assertEqual(
      getattr(toolchain_info, 'toolchains'),
      ['foo-default', 'bar-default', 'baz-nondefault'])


def GenTests(api):
  bapi_test_data = {
      'default_toolchains': ['foo-default', 'bar-default'],
      'nondefault_toolchains': ['baz-nondefault']
  }

  yield api.test(
      'basic',
      api.step_data('get toolchain info.read sdk_version.conf',
                    api.file.read_text(_TEST_SDK_VERSION_FILE)),
      api.cros_build_api.set_api_return(
          'get toolchain info', 'ToolchainService/GetToolchainsForBoard',
          data=json.dumps(bapi_test_data)),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'bad-sdk-conf',
      api.step_data('get toolchain info.read sdk_version.conf',
                    api.file.read_text('')),
      api.post_check(post_process.StepFailure, 'get toolchain info'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
