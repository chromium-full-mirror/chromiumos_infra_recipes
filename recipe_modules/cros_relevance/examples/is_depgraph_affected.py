# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.recipe_modules.chromeos.cros_relevance.examples.pointless import PointlessTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
    'cros_relevance',
    'cros_source',
    'gerrit',
    'src_state',
]


PROPERTIES = PointlessTest


def RunSteps(api, properties):
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)

  _ = api.cros_relevance.get_dependency_graph(sysroot, Chroot())
  dep_graph = depgraph.DepGraph(
      sysroot=sysroot, build_target=bt, package_deps=[
          depgraph.PackageDepInfo(dependency_source_paths=[
              depgraph.SourcePath(path='happy/source/dir'),
          ]),
      ])

  dep_graph_affected = api.cros_relevance.is_depgraph_affected(
      properties.gerrit_changes, bbcommon_pb2.GitilesCommit(id='my hash'),
      dep_graph, test_value=not properties.expected)
  api.assertions.assertEqual(not properties.expected, dep_graph_affected)


def GenTests(api):

  yield api.test(
      'affected',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], expected=False)),
  )

  yield api.test('not-affected', api.properties(PointlessTest(expected=True)))
