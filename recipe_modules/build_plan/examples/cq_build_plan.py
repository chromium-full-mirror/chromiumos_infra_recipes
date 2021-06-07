# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.recipe_modules.chromeos.build_plan.examples.cq_build_plan import (
    CqBuildPlanProperties)

from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_plan',
    'cros_infra_config',
    'cros_relevance',
    'git_footers',
]

PROPERTIES = CqBuildPlanProperties


def RunSteps(api, properties):
  child_specs = api.cros_infra_config.get_builder_config(
      'cq-orchestrator').orchestrator.child_specs
  completed_builds, existing_builds, new_requests = api.build_plan.get_build_plan(
      child_specs, True, [
          common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                  change=1234)
      ], common_pb2.GitilesCommit(), common_pb2.GitilesCommit())
  api.assertions.assertItemsEqual(existing_builds, [])
  actual_completed_builds = [x.builder.builder for x in completed_builds]
  api.assertions.assertItemsEqual(actual_completed_builds,
                                  properties.expected_completed_builds)
  actual_build_requests = [x.builder.builder for x in new_requests]
  api.assertions.assertItemsEqual(actual_build_requests,
                                  properties.expected_build_requests)
  api.assertions.assertEqual({x: True for x in properties.expected_experiments},
                             new_requests[0].experiments)


def GenTests(api):
  input_proto = api.build_plan.input_proto
  builds = [
      # Completed successfully.
      build_pb2.Build(id=8922054662172514000, builder={'builder': 'cave-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'cave')),
      # Slim parallel launch, completed successfully.
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-slim-cq'},
                      status=common_pb2.FAILURE, critical=False,
                      input=input_proto(None, 'amd64-generic-slim')),
      # Non-critical failure.
      build_pb2.Build(id=8922054662172514004, builder={'builder': 'coral-cq'},
                      status=common_pb2.FAILURE,
                      input=input_proto(None, 'coral')),
      # Non-critical failure.
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-cq'},
                      status=common_pb2.FAILURE,
                      input=input_proto(None, 'arm-generic')),
      # Broken before private builder.
      build_pb2.Build(id=8922054662172514002,
                      builder={'builder': 'atlas-slim-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'atlas-slim')),
      # Broken before private builder.
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'atlas')),
      # Broken before public builder.
      build_pb2.Build(id=8922054662172514003,
                      builder={'builder': 'arm64-generic-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'arm64-generic'))
  ]

  def cq_orchestrator_build_with_gerrit_change(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    build = api.buildbucket.ci_build_message(project='chromeos', **kwargs)
    build.input.gerrit_changes.extend([
        common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                change=1234)
    ])
    return api.buildbucket.build(build)

  yield api.test(
      'basic',
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-cq',
              'cave-cq',
          ],
      ),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'force-rebuild-non-critical-builder',
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
              'coral-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-cq',
              'cave-cq',
          ],
      ),
      api.git_footers.simulated_get_footers(['coral-cq'], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-cq',
          'coral-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'forced-rebuilds-all',
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
              'coral-cq',
              'amd64-generic-cq',
              'arm-generic-cq',
              'cave-cq',
          ], expected_completed_builds=[]),
      api.git_footers.simulated_get_footers(['all'], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-cq',
          'coral-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'experiments',
      cq_orchestrator_build_with_gerrit_change(
          experiments=['named-experiment-from-cq']),
      api.properties(
          expected_experiments=[
              'named-experiment-from-cq', 'named-exp-from-cl'
          ],
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ],
          expected_completed_builds=[
              'amd64-generic-cq',
              'cave-cq',
          ],
      ),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.git_footers.simulated_get_footers(['named-exp-from-cl'],
                                            'filter builds'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  config_ref = 'refs/changes/33/433/1'
  yield api.test(
      'with-config',
      cq_orchestrator_build_with_gerrit_change(
          bucket='staging', builder='staging-cq-orchestrator'),
      api.properties(
          expected_build_requests=[
              'atlas-cq',
              'arm64-generic-cq',
          ], expected_completed_builds=[
              'amd64-generic-cq',
              'cave-cq',
          ], **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(config_ref=config_ref),
          }),
      api.cros_infra_config.override_builder_configs_test_data(
          api.cros_infra_config.builder_configs_test_data, ref=config_ref,
          binaryproto=False),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  # TODO(crbug.com/1123776): Restore assertions to only expect the slim builder
  # after go/cros-slim-rollout parallel adoption.
  yield api.test(
      'slim-enabled',
      cq_orchestrator_build_with_gerrit_change(
          experiments=['enable_slim_builds']),
      api.properties(
          expected_experiments=['enable_slim_builds'], expected_build_requests=[
              'atlas-slim-cq',
              'atlas-cq',
              'arm64-generic-cq',
          ], expected_completed_builds=[
              'amd64-generic-cq',
              'cave-cq',
          ], **{"$chromeos/cros_relevance": {
              "enable_slim_builds": True
          }}),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-slim-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-slim-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  # TODO(crbug.com/187793586): Remove test case after go/cros-slim-rollout.
  yield api.test(
      'honor-slim-criticality',
      cq_orchestrator_build_with_gerrit_change(
          experiments=['enable_slim_builds', 'honor_slim_builder_criticality']),
      api.properties(
          expected_experiments=[
              'enable_slim_builds', 'honor_slim_builder_criticality'
          ], expected_build_requests=[
              'atlas-slim-cq',
              'arm64-generic-cq',
          ], expected_completed_builds=[
              'amd64-generic-cq',
              'cave-cq',
          ], **{
              "$chromeos/cros_relevance": {
                  "enable_slim_builds": True
              },
              "$chromeos/build_plan": {
                  "honor_slim_builder_criticality": True
              }
          }),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-slim-cq',
          'arm-generic-cq',
          'arm64-generic-cq',
          'atlas-slim-cq',
          'cave-cq',
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )
