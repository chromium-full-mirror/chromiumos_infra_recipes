# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'test_util',
]

from PB.chromiumos import common


def RunSteps(api):
  api.assertions.assertRaises(ValueError,
                              api.test_util.test_api.build_menu_properties,
                              build_target=common.BuildTarget(name='foo'),
                              build_target_name='bar')


def GenTests(api):
  yield api.test('basic')
