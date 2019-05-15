# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'naming',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.testplans.target_test_requirements_config import HwTestCfg


def RunSteps(api):
  build = build_pb2.Build(builder=build_pb2.BuilderID(
      project='foo', bucket='bar', builder='baz'), number=101)
  api.assertions.assertEqual(
      api.naming.get_build_title(build), 'foo.bar.baz.101')

  build = build_pb2.Build(builder=build_pb2.BuilderID(
      project='qux', bucket='quux', builder='quuz'), id=202)
  api.assertions.assertEqual(
      api.naming.get_build_title(build), 'qux.quux.quuz.202')

  hw_test = HwTestCfg.HwTest(skylab_board='target', suite='bvt-cq')
  api.assertions.assertEqual(
      api.naming.get_hw_test_title(hw_test), 'target.hw.bvt-cq')


def GenTests(api):
  yield api.test('basic')
