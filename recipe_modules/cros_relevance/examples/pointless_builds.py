# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot

DEPS = [
    'cros_relevance',
    'recipe_engine/properties',
]


def RunSteps(api):
  builder = 'builder'
  bt = BuildTarget(name='my_build_target')
  build_config = [dict(build_target=bt.name)]
  chroot = Chroot()
  gc = [
      bbcommon_pb2.GerritChange(change=123),
      bbcommon_pb2.GerritChange(change=456)
  ]
  api.cros_relevance.is_build_pointless(
      gc, bbcommon_pb2.GitilesCommit(id='my hash'), build_target=bt,
      chroot=chroot, test_is_pointless=False)
  api.cros_relevance.is_build_pointless(
      gc, bbcommon_pb2.GitilesCommit(id='my hash'), build_target=bt,
      chroot=chroot, test_is_pointless=True)


def GenTests(api):
  yield (api.test('pointless_check'))