# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'test_util',
]

from PB.chromiumos import common

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.assertions.assertRaises(ValueError,
                              api.test_util.test_api.build_menu_properties,
                              build_target=common.BuildTarget(name='foo'),
                              build_target_name='bar')


def GenTests(api):
  yield api.test('basic')
