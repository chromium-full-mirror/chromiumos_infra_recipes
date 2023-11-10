# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.recipe_modules.chromeos.cros_relevance.examples.build_plan import BuildPlanTest

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_relevance',
    'cros_source',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildPlanTest
_BUILDER_NAME = 'my little builder'


def RunSteps(api, properties):
  gc = [
      bbcommon_pb2.GerritChange(change=123, host='cr.googlesource.com'),
      bbcommon_pb2.GerritChange(change=456, host='cr.googlesource.com'),
  ] if api.cq.active else []
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
  builders_tuple = api.cros_relevance.run_build_planner(
      bc, gc, bbcommon_pb2.GitilesCommit(id='hello'),
      test_builder_ids=properties.test_builder_ids)
  api.assertions.assertCountEqual(builders_tuple.necessary,
                                  properties.expected_builders)
  api.assertions.assertCountEqual(builders_tuple.run_when_rules_skipped,
                                  properties.expected_skipped_builders)


def GenTests(api):
  yield api.test(
      'basic',
  )

  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='staging-release-main-orchestrator',
      ),
  )

  yield api.test(
      'my-little-builder',
      api.properties(
          BuildPlanTest(test_builder_ids=[BuilderConfig.Id(name=_BUILDER_NAME)],
                        expected_builders=[_BUILDER_NAME])))

  # Verify that simulated_run_build_planner works.
  yield api.test(
      'forced-response',
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'other-builder',
          ], skipped_builders=['skipped-builder']),
      api.properties(
          BuildPlanTest(expected_builders=[
              'other-builder',
          ], expected_skipped_builders=['skipped-builder'])))

  yield api.test(
      'branch',
      api.properties(
          BuildPlanTest(manifest_branch='BRANCH',
                        test_builder_ids=[BuilderConfig.Id(name=_BUILDER_NAME)],
                        expected_builders=[_BUILDER_NAME])),
  )

  yield api.test(
      'cq', api.cq(run_mode=api.cq.FULL_RUN), api.buildbucket.try_build(),
      api.properties(
          BuildPlanTest(
              test_builder_ids=[BuilderConfig.Id(name='amd64-generic-slim-cq')],
              expected_builders=['amd64-generic-slim-cq']),
      ))
