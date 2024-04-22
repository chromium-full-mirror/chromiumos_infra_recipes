# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the get_relevant_builder_configs function."""

from google.protobuf import json_format

from recipe_engine import post_process

from PB.chromite.api import relevancy as relevancy_pb2
from PB.chromiumos import builder_config as builder_config_pb2
from PB.chromiumos import common as common_pb2

from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_plan',
    'cros_build_api',
]



def RunSteps(api):
  gerrit_changes = [
      json_format.Parse(gc, bb_common_pb2.GerritChange())
      for gc in api.properties.get('input_changes', [])
  ] or [
      bb_common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                 change=1234)
  ]

  input_builder_configs = [
      json_format.Parse(bc, builder_config_pb2.BuilderConfig())
      for bc in api.properties.get('input_builder_configs', [])
  ]

  result = api.build_plan.get_relevant_builder_configs(input_builder_configs,
                                                       gerrit_changes)
  expected_builder_configs = [
      json_format.Parse(bc, builder_config_pb2.BuilderConfig())
      for bc in api.properties.get('expected_builder_configs', [])
  ]
  api.assertions.assertCountEqual(result, expected_builder_configs)


def GenTests(api):
  build_api_call_step = 'call chromite.api.RelevancyService/GetRelevantBuildTargets.call build API script'

  # Test BuilderConfigs.
  no_target_builder_config = builder_config_pb2.BuilderConfig(
      id=builder_config_pb2.BuilderConfig.Id(bucket='cq', name='some-util-cq',
                                             type='CQ'))

  target_a_builder_config = builder_config_pb2.BuilderConfig(
      id=builder_config_pb2.BuilderConfig.Id(bucket='cq', name='target-a-cq',
                                             type='CQ'),
      build_target=common_pb2.BuildTarget(
          name='a', profile=common_pb2.Profile(name='BASE')))

  target_a_other_profile_builder_config = builder_config_pb2.BuilderConfig(
      id=builder_config_pb2.BuilderConfig.Id(bucket='cq',
                                             name='target-a-other-cq',
                                             type='CQ'),
      build_target=common_pb2.BuildTarget(
          name='a', profile=common_pb2.Profile(name='OTHER')))

  target_a_bazel_builder_config = builder_config_pb2.BuilderConfig(
      id=builder_config_pb2.BuilderConfig.Id(bucket='cq',
                                             name='target-a-bazel-cq',
                                             type='CQ'),
      build=builder_config_pb2.BuilderConfig.Build(
          build_images=builder_config_pb2.BuilderConfig.Build.BuildImages(
              build_images_orchestrator='BAZEL')),
      build_target=common_pb2.BuildTarget(
          name='a', profile=common_pb2.Profile(name='BASE')))

  target_b_builder_config = builder_config_pb2.BuilderConfig(
      id=builder_config_pb2.BuilderConfig.Id(bucket='cq', name='target-b-cq',
                                             type='CQ'),
      build_target=common_pb2.BuildTarget(
          name='b', profile=common_pb2.Profile(name='BASE')))

  # Test that it calls the right things.
  yield api.test(
      'basic',
      api.post_check(post_process.MustRun, 'gerrit-fetch-changes'),
      api.post_check(post_process.MustRun, 'get affected paths'),
      api.post_check(post_process.MustRun, build_api_call_step),
      api.post_process(post_process.DropExpectation),
  )

  # Test that it calls the right things.
  yield api.test(
      'returns-all-on-failure',
      api.step_data(build_api_call_step, retcode=1),
      api.post_check(post_process.MustRun, 'gerrit-fetch-changes'),
      api.post_check(post_process.MustRun, 'get affected paths'),
      api.post_check(post_process.MustRun, build_api_call_step),
      api.properties(
          input_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
              json_format.MessageToJson(target_b_builder_config),
          ], expected_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
              json_format.MessageToJson(target_b_builder_config),
          ]),
      api.post_process(post_process.DropExpectation),
  )

  build_api_return_val = json_format.MessageToJson(
      relevancy_pb2.GetRelevantBuildTargetsResponse(build_targets=[
          relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget(
              build_target=common_pb2.BuildTarget(
                  name='b', profile=common_pb2.Profile(name='BASE')))
      ]))

  yield api.test(
      'distinguish-between-target-name',
      api.properties(
          input_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
              json_format.MessageToJson(target_b_builder_config),
          ], expected_builder_configs=[
              json_format.MessageToJson(target_b_builder_config),
          ]),
      api.cros_build_api.set_api_return(
          parent_step_name='',
          endpoint='RelevancyService/GetRelevantBuildTargets',
          data=build_api_return_val),
      api.post_process(post_process.DropExpectation),
  )

  build_api_return_val = json_format.MessageToJson(
      relevancy_pb2.GetRelevantBuildTargetsResponse(build_targets=[
          relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget(
              build_target=common_pb2.BuildTarget(
                  name='b', profile=common_pb2.Profile(name='BASE'))),
          relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget(
              build_target=common_pb2.BuildTarget(
                  name='a', profile=common_pb2.Profile(name='OTHER')))
      ]))
  yield api.test(
      'distinguish-between-profiles',
      api.properties(
          input_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
              json_format.MessageToJson(target_b_builder_config)
          ], expected_builder_configs=[
              json_format.MessageToJson(target_b_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
          ]),
      api.cros_build_api.set_api_return(
          parent_step_name='',
          endpoint='RelevancyService/GetRelevantBuildTargets',
          data=build_api_return_val),
      api.post_process(post_process.DropExpectation),
  )

  build_api_return_val = json_format.MessageToJson(
      relevancy_pb2.GetRelevantBuildTargetsResponse(build_targets=[
          relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget(
              build_target=common_pb2.BuildTarget(
                  name='a', profile=common_pb2.Profile(name='BASE')))
      ]))
  yield api.test(
      'same-build-target-across-builders',
      api.properties(
          input_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
              json_format.MessageToJson(target_a_bazel_builder_config),
              json_format.MessageToJson(target_b_builder_config)
          ], expected_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_bazel_builder_config),
          ]),
      api.cros_build_api.set_api_return(
          parent_step_name='',
          endpoint='RelevancyService/GetRelevantBuildTargets',
          data=build_api_return_val),
      api.post_process(post_process.DropExpectation),
  )

  build_api_return_val = json_format.MessageToJson(
      relevancy_pb2.GetRelevantBuildTargetsResponse(build_targets=[]))
  yield api.test(
      'no-build-target',
      api.properties(
          input_builder_configs=[
              json_format.MessageToJson(no_target_builder_config),
          ], expected_builder_configs=[
              json_format.MessageToJson(no_target_builder_config),
          ]),
      api.cros_build_api.set_api_return(
          parent_step_name='',
          endpoint='RelevancyService/GetRelevantBuildTargets',
          data=build_api_return_val),
      api.post_process(post_process.DropExpectation),
  )

  build_api_return_val = json_format.MessageToJson(
      relevancy_pb2.GetRelevantBuildTargetsResponse(build_targets=[]))
  yield api.test(
      'src-bazel-change',
      api.properties(
          input_builder_configs=[
              json_format.MessageToJson(target_a_builder_config),
              json_format.MessageToJson(target_a_other_profile_builder_config),
              json_format.MessageToJson(target_a_bazel_builder_config),
              json_format.MessageToJson(target_b_builder_config)
          ], expected_builder_configs=[
              json_format.MessageToJson(target_a_bazel_builder_config),
          ], input_changes=[
              json_format.MessageToJson(
                  bb_common_pb2.GerritChange(project='chromiumos/bazel'))
          ]),
      api.cros_build_api.set_api_return(
          parent_step_name='',
          endpoint='RelevancyService/GetRelevantBuildTargets',
          data=build_api_return_val),
      api.post_process(post_process.DropExpectation),
  )
