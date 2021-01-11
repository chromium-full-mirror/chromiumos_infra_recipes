# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
    'cros_source',
    'src_state',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.recipe_modules.chromeos.cros_relevance.examples.build_plan import (
    BuildPlanTest)
from recipe_engine import post_process

PROPERTIES = BuildPlanTest
_BUILDER_NAME = 'my little builder'


def RunSteps(api, properties):
  gc = [
      bbcommon_pb2.GerritChange(change=123),
      bbcommon_pb2.GerritChange(change=456)
  ]
  bc = [
      BuilderConfig(
          id=BuilderConfig.Id(name=_BUILDER_NAME),
          general=BuilderConfig.General(
              run_when=BuilderConfig.General.RunWhen(
                  mode=BuilderConfig.General.RunWhen.ALWAYS_RUN,
              )))
  ]
  if properties.manifest_branch:
    api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                    properties.manifest_branch)
  builders = api.cros_relevance.get_necessary_builders(
      bc, gc, bbcommon_pb2.GitilesCommit(id='hello'),
      test_builder_ids=properties.test_builder_ids)
  api.assertions.assertItemsEqual(builders, properties.expected_builders)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StepCommandContains,
                     'plan builds.ensure binaries.ensure_installed',
                     ['chromiumos/infra/test_planner latest']),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{"$chromeos/cros_relevance": {
              "test_planner_cipd_ref": "foo"
          }}),
      api.post_check(post_process.StepCommandContains,
                     'plan builds.ensure binaries.ensure_installed',
                     ['chromiumos/infra/test_planner foo']),
  )

  yield api.test(
      'my-little-builder',
      api.properties(
          BuildPlanTest(test_builder_ids=[BuilderConfig.Id(name=_BUILDER_NAME)],
                        expected_builders=[_BUILDER_NAME])))

  # Verify that simulated_get_necessary_builders works.
  yield api.test(
      'forced-response',
      api.cros_relevance.simulated_get_necessary_builders([
          'other-builder',
      ]), api.properties(BuildPlanTest(expected_builders=[
          'other-builder',
      ])))

  yield api.test(
      'branch',
      api.properties(
          BuildPlanTest(manifest_branch='BRANCH',
                        test_builder_ids=[BuilderConfig.Id(name=_BUILDER_NAME)],
                        expected_builders=[_BUILDER_NAME])),
      #api.post_check(
      #    post_process.MustRun,
      #    'pointless build check.depgraph relevance check.run check'),
  )
