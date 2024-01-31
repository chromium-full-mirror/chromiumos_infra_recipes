# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the run_build_planner function."""

from google.protobuf import json_format

from PB.chromiumos.common import ProtoBytes as common_proto_bytes
from PB.chromiumos import generate_build_plan as generate_build_plan_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.recipe_modules.chromeos.cros_relevance.examples.build_plan import BuildPlanTest

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_relevance',
    'cros_source',
    'src_state',
]


PROPERTIES = BuildPlanTest

def RunSteps(api, properties):
  if properties.manifest_branch:
    api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                    properties.manifest_branch)

  builders_tuple = api.cros_relevance.run_build_planner(
      builder_configs=[
          BuilderConfig(id=bid) for bid in properties.test_builder_ids
      ], gerrit_changes=api.buildbucket.build.input.gerrit_changes,
      gitiles_commit=bbcommon_pb2.GitilesCommit(id='hello'))
  api.assertions.assertCountEqual(builders_tuple.necessary,
                                  properties.expected_builders)
  api.assertions.assertCountEqual(builders_tuple.run_when_rules_skipped,
                                  properties.expected_skipped_builders)


def GenTests(api):

  # Test that the build planner is called with the correct inputs.
  expected_request = generate_build_plan_pb2.GenerateBuildPlanRequest(
      builder_configs=[
          BuilderConfig(id=BuilderConfig.Id(name='needed-builder'))
      ], gitiles_commit=common_proto_bytes(
          serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
              bbcommon_pb2.GitilesCommit(id='hello'))))
  yield api.test(
      'basic',
      api.properties(
          BuildPlanTest(
              test_builder_ids=[
                  BuilderConfig.Id(name='needed-builder'),
              ], expected_builders=['needed-builder'])),
      api.post_process(
          post_process.StepCommandContains,
          'plan builds.run planner',
          [
              '[START_DIR]/cipd/build_plan_generator/build_plan_generator',
              'generate-plan', '--input_binary_pb',
              '[CLEANUP]/build-plan-_tmp_1/input.binaryproto',
              '--output_binary_pb',
              '[CLEANUP]/build-plan-_tmp_1/output.binaryproto'
          ],
      ),
      api.post_check(post_process.LogContains, 'plan builds', 'planner_input',
                     [json_format.MessageToJson(expected_request)]),
      api.post_process(post_process.DropExpectation),
  )

  gerrit_change = bbcommon_pb2.GerritChange(change=123,
                                            host='cr.googlesource.com')
  expected_request = generate_build_plan_pb2.GenerateBuildPlanRequest(
      builder_configs=[
          BuilderConfig(id=BuilderConfig.Id(name='amd64-generic-cq'))
      ], gitiles_commit=common_proto_bytes(
          serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
              bbcommon_pb2.GitilesCommit(id='hello'))),
      gerrit_changes=[
          common_proto_bytes(
              serialized_proto=bbcommon_pb2.GerritChange.SerializeToString(
                  gerrit_change))
      ])
  yield api.test(
      'with-gerrit-changes',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(gerrit_changes=[gerrit_change]),
      api.properties(
          BuildPlanTest(
              test_builder_ids=[BuilderConfig.Id(name='amd64-generic-cq')],
              expected_builders=['amd64-generic-cq']),
      ),
      api.post_check(post_process.LogContains, 'plan builds', 'planner_input',
                     [json_format.MessageToJson(expected_request)]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'manifest-branch-passes-in-manifest-file',
      api.properties(
          BuildPlanTest(
              manifest_branch='BRANCH',
              test_builder_ids=[BuilderConfig.Id(name='needed-builder')],
              expected_builders=['needed-builder'])),
      api.post_process(
          post_process.StepCommandContains,
          'plan builds.run planner',
          ['--manifest_file'],
      ),
      api.post_process(post_process.DropExpectation),
  )

  # Test the test planner return values.
  yield api.test(
      'skipped-and-needed',
      api.properties(
          BuildPlanTest(
              test_builder_ids=[
                  BuilderConfig.Id(name='needed-builder'),
                  BuilderConfig.Id(name='skipped-builder')
              ], expected_builders=['needed-builder'],
              expected_skipped_builders=['skipped-builder'])),
      api.step_data(
          'plan builds.read output file',
          api.file.read_raw(
              generate_build_plan_pb2.GenerateBuildPlanResponse(
                  builds_to_run=[BuilderConfig.Id(name='needed-builder')],
                  skip_for_run_when_rules=[
                      BuilderConfig.Id(name='skipped-builder')
                  ]).SerializeToString())),
      api.post_process(post_process.DropExpectation),
  )

  # Verify that simulated_run_build_planner works.
  yield api.test(
      'test-override',
      api.cros_relevance.simulated_run_build_planner(
          necessary_builders=[
              'other-builder',
          ], skipped_builders=['skipped-builder']),
      api.properties(
          BuildPlanTest(expected_builders=[
              'other-builder',
          ], expected_skipped_builders=['skipped-builder'])),
      api.post_process(post_process.DropExpectation),
  )
