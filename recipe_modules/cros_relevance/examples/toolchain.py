# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.chromiumos.common import Chroot
from PB.recipe_modules.chromeos.cros_relevance.examples.toolchain import (
    ToolchainTest)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = ToolchainTest


def RunSteps(api, properties):
  chroot = Chroot()

  gitiles_commit = bbcommon_pb2.GitilesCommit(id='my hash')

  api.cros_relevance.check_for_toolchain_change(
      properties.gerrit_changes, gitiles_commit, chroot,
      test_value=properties.expected_toolchain_changed)
  api.assertions.assertEqual(properties.expected_toolchain_changed,
                             api.cros_relevance.toolchain_cls_applied)


def GenTests(api):

  yield api.test(
      'no-toolchain-cls',
      api.properties(
          ToolchainTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456)
              ], expected_toolchain_changed=True)))

  yield api.test(
      'toolchain-cls',
      api.properties(
          ToolchainTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456)
              ], expected_toolchain_changed=False)))

  yield api.test(
      'no-cls', api.properties(ToolchainTest(expected_toolchain_changed=False)))

  yield api.test('test-value', api.cros_relevance.toolchain_cls_applied(True),
                 api.properties(ToolchainTest(expected_toolchain_changed=True)))
