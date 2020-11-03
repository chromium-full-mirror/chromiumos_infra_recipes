# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
    'cros_source',
    'src_state',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.recipe_modules.chromeos.cros_relevance.examples.pointless import (
    PointlessTest)

from recipe_engine import post_process

PROPERTIES = PointlessTest


def RunSteps(api, properties):
  is_cq = (properties.is_cq if properties.is_cq else False)
  config = BuilderConfig()
  if is_cq:
    config.id.type = BuilderConfig.Id.CQ
  force_relevant = (
      properties.force_relevant if properties.force_relevant else False)
  if properties.manifest_branch:
    api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                    properties.manifest_branch)
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
      dep_graph=dep_graph, config=config, force_relevant=force_relevant,
      test_value=properties.expected)
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
              ], is_cq=True, expected=False)),
      api.post_check(
          post_process.MustRun,
          'pointless build check.depgraph relevance check.run check'),
  )

  yield api.test(
      'relevant-branch',
      api.properties(
          PointlessTest(
              manifest_branch='BRANCH', gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], is_cq=True, expected=False)),
      api.post_check(
          post_process.MustRun,
          'pointless build check.depgraph relevance check.run check'),
  )

  yield api.test(
      'relevant-force-relevant',
      api.properties(
          PointlessTest(force_relevant=True, is_cq=True, expected=False)))

  yield api.test(
      'pointless',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], is_cq=True, expected=True)))

  yield api.test(
      'pointless-cq-no-changes',
      api.properties(
          PointlessTest(gerrit_changes=[], is_cq=True, expected=True)))

  yield api.test('relevant-non-cq',
                 api.properties(PointlessTest(is_cq=False, expected=False)))
