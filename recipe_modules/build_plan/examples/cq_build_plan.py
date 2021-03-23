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
  api.assertions.assertEqual(existing_builds, [])
  api.assertions.assertEqual(len(completed_builds), 1)
  api.assertions.assertEqual(completed_builds[0].builder.builder,
                             'amd64-generic-cq')
  # TODO(crbug.com/1123776): Restore assertions to only expect the slim builder
  # after go/cros-slim-rollout parallel adoption.
  api.assertions.assertEqual(len(new_requests), 3)
  api.assertions.assertItemsEqual([
      new_requests[0].builder.builder, new_requests[1].builder.builder,
      new_requests[2].builder.builder
  ], ['atlas-slim-cq', 'atlas-cq', 'arm64-generic-cq'])
  api.assertions.assertEqual({x: True for x in properties.expected_experiments},
                             new_requests[0].experiments)


def GenTests(api):
  input_proto = api.build_plan.input_proto
  builds = [
      # Not scheduled, non-critical
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'amd64-generic')),
      # Not scheduled, waiting for existing
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-cq'},
                      status=common_pb2.STARTED,
                      input=input_proto(None, 'arm-generic')),
      # Scheduled using internal manifest
      build_pb2.Build(id=8922054662172514002,
                      builder={'builder': 'atlas-slim-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'atlas-slim')),
      # Scheduled using public manifest
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
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq', 'arm-generic-cq', 'arm64-generic-cq',
          'atlas-slim-cq'
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
      api.properties(expected_experiments=[
          'named-experiment-from-cq', 'named-exp-from-cl'
      ]),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.git_footers.simulated_get_footers(['named-exp-from-cl'],
                                            'filter builds'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq', 'arm-generic-cq', 'arm64-generic-cq',
          'atlas-slim-cq'
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
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(config_ref=config_ref)
          }),
      api.cros_infra_config.override_builder_configs_test_data(
          api.cros_infra_config.builder_configs_test_data, ref=config_ref,
          binaryproto=False),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq', 'arm-generic-cq', 'arm64-generic-cq',
          'atlas-slim-cq'
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )

  yield api.test(
      'public-builders-sync-public-manifest',
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(switch_to_external_manifest=True)
          }),
      api.git_footers.simulated_get_footers([], 'get build history'),
      api.cros_relevance.simulated_get_necessary_builders([
          'amd64-generic-cq', 'arm-generic-cq', 'arm64-generic-cq',
          'atlas-slim-cq'
      ]),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.get completed builds.'
          'get change build history.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds, 'get build history.find matching builds.'
          'buildbucket.search'),
  )
