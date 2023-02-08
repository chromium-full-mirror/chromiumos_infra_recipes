# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_plan.examples.cq_build_plan import (
    CqBuildPlanProperties)

from recipe_engine import post_process

from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'build_plan',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CqBuildPlanProperties


def RunSteps(api, properties):
  child_specs = api.cros_infra_config.get_builder_config(
      'cq-orchestrator').orchestrator.child_specs
  _, _, new_requests = api.build_plan.get_build_plan(
      child_specs, True, api.cros_infra_config.gerrit_changes,
      common_pb2.GitilesCommit(id='original'),
      common_pb2.GitilesCommit(id='original'))

  enabled_experiments = {
      exp: enabled
      for exp, enabled in new_requests[0].experiments.items()
      if enabled
  }
  api.assertions.assertEqual({x: True for x in properties.expected_experiments},
                             enabled_experiments)
  # SHAs for new builds should be unchanged for a CQ looks dryrun.
  for request in new_requests:
    api.assertions.assertEqual('original', request.gitiles_commit.id)


def GenTests(api):

  def cq_orchestrator_build_with_gerrit_change(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    return api.buildbucket.try_build(project='chromeos', **kwargs)

  build_input = build_pb2.Build.Input()
  build_input.gitiles_commit.id = 'sampleSHA'

  output = build_pb2.Build.Output()
  output.properties['greenness'] = {'aggregateMetric': 90}

  # Choosing timestamps based on time module's default test data.
  test_start_timestamp = timestamp_pb2.Timestamp(seconds=1336972527)
  test_end_timestamp = timestamp_pb2.Timestamp(seconds=1336997427)

  green_build = build_pb2.Build(id=123, output=output,
                                start_time=test_start_timestamp,
                                end_time=test_end_timestamp)

  output.properties['greenness'] = {'aggregateMetric': 60}
  red_build = build_pb2.Build(id=234, output=output,
                              start_time=test_start_timestamp,
                              end_time=test_end_timestamp)

  yield api.test(
      'green',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.cros_infra_config.cq_looks']),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'dry_run': True
          }}, expected_experiments=['chromeos.cros_infra_config.cq_looks']),
      api.buildbucket.simulated_search_results(
          builds=[green_build],
          step_name='filter builds.looks for green.checking latest snapshot greenness.buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DoesNotRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'fallback-to-green',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.cros_infra_config.cq_looks']),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'dry_run': True
          }}, expected_experiments=['chromeos.cros_infra_config.cq_looks']),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.checking latest snapshot greenness.buildbucket.search'
      ),
      api.buildbucket.simulated_search_results(
          builds=[green_build, red_build],
          step_name='filter builds.looks for green.find green snapshot.buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_check(
          post_process.MustRun,
          'filter builds.looks for green.find green snapshot.set looks_for_green'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-green',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.cros_infra_config.cq_looks']),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'dry_run': True
          }}, expected_experiments=['chromeos.cros_infra_config.cq_looks']),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.checking latest snapshot greenness.buildbucket.search'
      ),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.find green snapshot.buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_process(post_process.DropExpectation),
  )
