# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.analysis.proto.v1.common import Variant

DEPS = [
    'recipe_engine/assertions',
    'rdb_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  variant = Variant()
  empty_bt = api.rdb_util.get_build_target_from_variant(variant)
  api.assertions.assertEqual(empty_bt, '')
  getattr(variant, 'def')['build_target'] = 'eve'
  bt = api.rdb_util.get_build_target_from_variant(variant)
  api.assertions.assertEqual(bt, 'eve')


def GenTests(api):
  yield api.test('basic')
