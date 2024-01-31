# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.analysis.proto.v1.common import Variant

DEPS = [
    'recipe_engine/assertions',
    'rdb_util',
]



def RunSteps(api):
  variant = Variant()
  empty_bt = api.rdb_util.get_model_from_variant(variant)
  api.assertions.assertEqual(empty_bt, '')
  getattr(variant, 'def')['model'] = 'eve'
  bt = api.rdb_util.get_model_from_variant(variant)
  api.assertions.assertEqual(bt, 'eve')


def GenTests(api):
  yield api.test('basic')
