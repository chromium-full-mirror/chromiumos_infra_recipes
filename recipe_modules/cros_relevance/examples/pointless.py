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
from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.recipe_modules.chromeos.cros_relevance.examples.pointless import (
    PointlessTest)

PROPERTIES = PointlessTest


def RunSteps(api, properties):
  builder = 'builder'
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)
  dep_graph = depgraph.DepGraph(
      sysroot=sysroot, build_target=bt, package_deps=[
          depgraph.PackageDepInfo(dependency_source_paths=[
              depgraph.SourcePath(path='happy/source/dir'),
          ]),
      ])

  pointless = api.cros_relevance.is_build_pointless(
      properties.gerrit_changes, bbcommon_pb2.GitilesCommit(id='my hash'),
      dep_graph=dep_graph, test_value=properties.expected)
  api.assertions.assertEqual(properties.expected, pointless)
  api.cros_relevance.get_dependency_graph(sysroot, Chroot())


def GenTests(api):

  yield api.test(
      'relevant',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], expected=False)))

  yield api.test(
      'pointless',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], expected=True)))

  yield api.test('no-changes', api.properties(PointlessTest(expected=False)))
