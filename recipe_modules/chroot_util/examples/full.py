# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'chroot_util',
]

from PB.recipe_modules.chromeos.chroot_util.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(api.chroot_util.chroot, None)
  chroot = api.chroot_util.init_sdk(version=properties.sdk_version)
  api.assertions.assertNotEqual(chroot, None)
  api.assertions.assertEqual(chroot, api.chroot_util.chroot)


def GenTests(api):
  yield api.test('basic')

  yield (api.test('versioned') +  #
         api.properties(TestInputProperties(sdk_version=3)) +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "1"}')))
