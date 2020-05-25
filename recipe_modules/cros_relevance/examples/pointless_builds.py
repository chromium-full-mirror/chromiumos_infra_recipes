# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.testplans.pointless_build import PointlessBuildCheckResponse

DEPS = ['cros_relevance', 'recipe_engine/properties', 'recipe_engine/file']


def RunSteps(api):
  builder = 'builder'
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)
  build_config = [dict(build_target=bt.name)]
  chroot = Chroot()
  dep_graph = depgraph.DepGraph(
      sysroot=sysroot, build_target=bt, package_deps=[
          depgraph.PackageDepInfo(dependency_source_paths=[
              depgraph.SourcePath(path='happy/source/dir'),
          ]),
      ])

  gc = [
      bbcommon_pb2.GerritChange(change=123),
      bbcommon_pb2.GerritChange(change=456)
  ]
  no_gc = []
  api.cros_relevance.is_build_pointless(
      gc, bbcommon_pb2.GitilesCommit(id='my hash'), dep_graph=dep_graph)
  api.cros_relevance.is_build_pointless(
      no_gc, bbcommon_pb2.GitilesCommit(id='my hash'), dep_graph=dep_graph)
  api.cros_relevance.get_dependency_graph(sysroot, chroot)


def GenTests(api):

  def force_pointless_check_response(api, pointless_status=True):
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = pointless_status
    serialized = resp.SerializeToString()
    return api.step_data(
        'pointless build check.depgraph relevance check.read output file',
        api.file.read_raw(content=serialized))

  yield api.test('not pointless_check')

  yield api.test('pointless check', force_pointless_check_response(api, True))
