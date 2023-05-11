# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'rdb_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  suite_name = api.rdb_util.get_suite('betty-cq.tast_vm.tast_vm_default')
  api.assertions.assertEqual(suite_name, 'tast_vm_default')
  suite_name = api.rdb_util.get_suite('zork-cq.hw.bvt-inline')
  api.assertions.assertEqual(suite_name, 'bvt-inline')
  suite_name = api.rdb_util.get_suite(
      'betty-cq.tast_vm.tast_vm_default_shard_5_of_5')
  api.assertions.assertEqual(suite_name, 'tast_vm_default')


def GenTests(api):
  yield api.test('basic')
