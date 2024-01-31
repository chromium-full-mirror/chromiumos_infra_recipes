# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.recipe_modules.chromeos.cros_relevance.examples.pointless import PointlessTest

from recipe_engine import post_process

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

  patch_sets = api.gerrit.fetch_patch_sets(properties.gerrit_changes)
  relevant = api.cros_relevance.is_cq_build_relevant(
      patch_sets, dep_graph, force_relevant,
      is_pointless_test_value=properties.expected)
  api.assertions.assertEqual(not properties.expected, relevant)


def GenTests(api):

  yield api.test(
      'relevant',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], expected=False)),
      api.post_check(post_process.MustRun, 'cq relevance check.run check'),
  )

  yield api.test(
      'relevant-branch',
      api.properties(
          PointlessTest(
              manifest_branch='BRANCH', gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], expected=False)),
      api.post_check(post_process.MustRun, 'cq relevance check.run check'),
  )

  yield api.test(
      'relevant-force-relevant',
      api.properties(PointlessTest(force_relevant=True, expected=False)))

  yield api.test(
      'pointless',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], expected=True)))

  yield api.test(
      'pointless-cq-no-changes',
      api.properties(PointlessTest(gerrit_changes=[], expected=True)))
