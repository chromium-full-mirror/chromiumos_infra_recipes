# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.chromiumos.common import Chroot

DEPS = [
    'cros_relevance',
    'recipe_engine/assertions',
]


def RunSteps(api):
  chroot = Chroot()

  gc = [
      bbcommon_pb2.GerritChange(change=123),
      bbcommon_pb2.GerritChange(change=456)
  ]

  no_gc = []

  gitiles_commit = bbcommon_pb2.GitilesCommit(id='my hash')

  toolchain_changed_no_gc = api.cros_relevance.check_for_toolchain_change(
      no_gc, gitiles_commit, chroot)
  api.assertions.assertFalse(toolchain_changed_no_gc)

  toolchain_changed = api.cros_relevance.check_for_toolchain_change(
      gc, gitiles_commit, chroot)


def GenTests(api):
  yield api.test('toolchain_change_check')
