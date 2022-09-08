# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
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

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = PointlessTest


def RunSteps(api, properties):
  config = BuilderConfig()
  if properties.config_type:
    config.id.type = properties.config_type
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

  if config.id.type == BuilderConfig.Id.POSTSUBMIT:
    pointless = not api.cros_relevance.postsubmit_relevance_check(
        bbcommon_pb2.GitilesCommit(id='my hash'), dep_graph)
  else:
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
              ], config_type=BuilderConfig.Id.CQ, expected=False)),
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
              ], config_type=BuilderConfig.Id.CQ, expected=False)),
      api.post_check(
          post_process.MustRun,
          'pointless build check.depgraph relevance check.run check'),
  )

  yield api.test(
      'relevant-force-relevant',
      api.properties(
          PointlessTest(force_relevant=True, config_type=BuilderConfig.Id.CQ,
                        expected=False)))

  yield api.test(
      'pointless',
      api.properties(
          PointlessTest(
              gerrit_changes=[
                  bbcommon_pb2.GerritChange(change=123),
                  bbcommon_pb2.GerritChange(change=456),
              ], config_type=BuilderConfig.Id.CQ, expected=True)))

  yield api.test(
      'pointless-cq-no-changes',
      api.properties(
          PointlessTest(gerrit_changes=[], config_type=BuilderConfig.Id.CQ,
                        expected=True)))

  yield api.test('relevant-non-cq',
                 api.properties(PointlessTest(expected=False)))

  yield api.test(
      'force-postsubmit-relevant',
      api.properties(
          PointlessTest(config_type=BuilderConfig.Id.POSTSUBMIT,
                        expected=False)),
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'postsubmit relevance check'),
  )

  yield api.test(
      'postsubmit-relevant',
      api.properties(
          PointlessTest(config_type=BuilderConfig.Id.POSTSUBMIT,
                        expected=True)),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'postsubmit relevance check'),
  )
