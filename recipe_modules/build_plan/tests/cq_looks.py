# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_plan.tests.cq_looks import \
  CqLooksProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'build_plan',
    'cros_infra_config',
    'gerrit',
    'git_footers',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

INTERNAL_HOST_URL = 'chrome-internal.googlesource.com'
EXTERNAL_HOST_URL = 'chromium.googlesource.com'

ORIGINAL_INTERNAL_SHA = 'internalSHA'
ORIGINAL_EXTERNAL_SHA = 'externalSHA'

MODIFIED_INTERNAL_SHA = 'i' * 40
MODIFIED_EXTERNAL_SHA = 'e' * 40

PROPERTIES = CqLooksProperties


def RunSteps(api, properties):
  expected_internal_sha = properties.expected_internal_sha or ORIGINAL_INTERNAL_SHA
  expected_external_sha = properties.expected_external_sha or ORIGINAL_EXTERNAL_SHA
  child_specs = api.cros_infra_config.get_builder_config(
      'cq-orchestrator').orchestrator.child_specs
  _, new_requests = api.build_plan.get_build_plan(
      child_specs, True, api.cros_infra_config.gerrit_changes,
      common_pb2.GitilesCommit(id=ORIGINAL_INTERNAL_SHA,
                               host=INTERNAL_HOST_URL),
      common_pb2.GitilesCommit(id=ORIGINAL_EXTERNAL_SHA,
                               host=EXTERNAL_HOST_URL))

  for request in new_requests:
    if request.gitiles_commit.host == INTERNAL_HOST_URL:
      api.assertions.assertEqual(expected_internal_sha,
                                 request.gitiles_commit.id)
    elif request.gitiles_commit.host == EXTERNAL_HOST_URL:
      api.assertions.assertEqual(expected_external_sha,
                                 request.gitiles_commit.id)


def GenTests(api):

  def cq_orchestrator_build_with_gerrit_change(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    return api.buildbucket.try_build(project='chromeos', **kwargs)

  build_input = build_pb2.Build.Input()
  build_input.gitiles_commit.id = MODIFIED_INTERNAL_SHA
  build_input.gitiles_commit.host = INTERNAL_HOST_URL

  output = build_pb2.Build.Output()
  output.properties['greenness'] = {'aggregateBuildMetric': 90}

  # Choosing timestamps based on time module's default test data.
  test_start_timestamp = timestamp_pb2.Timestamp(seconds=1336972527)
  test_end_timestamp = timestamp_pb2.Timestamp(seconds=1336997427)

  green_internal_build = build_pb2.Build(id=123, output=output,
                                         input=build_input,
                                         start_time=test_start_timestamp,
                                         end_time=test_end_timestamp)

  output.properties['greenness'] = {'aggregateBuildMetric': 60}
  red_build = build_pb2.Build(id=234, output=output,
                              start_time=test_start_timestamp,
                              end_time=test_end_timestamp)

  yield api.test(
      'switch-to-green',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'enable_looks_for_green': True
          }}, expected_internal_sha=MODIFIED_INTERNAL_SHA,
          expected_external_sha=MODIFIED_EXTERNAL_SHA),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check disallow looks for green'
      ),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check if CL uses Cq-Depend'
      ),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.buildbucket.simulated_search_results(
          builds=[green_internal_build, red_build],
          step_name='filter builds.looks for green.find green snapshot.buildbucket.search'
      ),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.set green snapshot'),
      api.post_check(
          post_process.MustRun,
          'filter builds.looks for green.find green snapshot.set looks_for_green'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'filter builds.looks for green.checking mergability.resetting to original snapshot'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'use-complete-snapshot',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          ),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'enable_looks_for_green': True,
              'use_complete_snapshot': True
          }},
          expected_internal_sha=MODIFIED_INTERNAL_SHA, expected_external_sha=MODIFIED_EXTERNAL_SHA),
      api.git_footers.simulated_get_footers([], 'filter builds.check should look for green.check disallow looks for green'),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check if CL uses Cq-Depend'
      ),
      api.buildbucket.simulated_search_results(
          builds=[green_internal_build, red_build],
          step_name='filter builds.looks for green.find green snapshot.buildbucket.search'
      ),
      api.post_check(post_process.DoesNotRun,
                     'filter builds.looks for green.checking latest green snapshot'),  # skipped for use_complete_snapshot
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.set green snapshot'),
      api.post_check(
          post_process.MustRun,
          'filter builds.looks for green.find green snapshot.set looks_for_green'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'change-incompatible-with-older-snap',
      api.gerrit.simulated_changes_are_submittable(
          submittable=False,
          step_name_prefix='filter builds.looks for green.checking mergability'
      ),
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'enable_looks_for_green': True
          }},
      ),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check disallow looks for green'
      ),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check if CL uses Cq-Depend'
      ),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.buildbucket.simulated_search_results(
          builds=[green_internal_build, red_build],
          step_name='filter builds.looks for green.find green snapshot.buildbucket.search'
      ),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.set green snapshot'),
      api.post_check(
          post_process.MustRun,
          'filter builds.looks for green.find green snapshot.set looks_for_green'
      ),
      api.post_check(
          post_process.MustRun,
          'filter builds.looks for green.checking mergability.git checkout'),
      api.post_check(
          post_process.MustRun,
          'filter builds.looks for green.checking mergability.resetting to original snapshot.git checkout'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'lfg-disabled',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(),
      api.post_check(
          post_process.DoesNotRun,
          'filter builds.looks for green.checking latest scored snapshot'),
      api.post_check(post_process.DoesNotRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'lfg-disallow-footer',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'enable_looks_for_green': True,
          }},
      ),
      api.git_footers.simulated_get_footers([
          'True'
      ], 'filter builds.check should look for green.check disallow looks for green'
                                           ),
      api.post_check(post_process.StatusSuccess),
      api.post_check(
          post_process.MustRun,
          'filter builds.check should look for green.check disallow looks for green'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'filter builds.looks for green.checking latest scored snapshot'),
      api.post_check(post_process.DoesNotRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-green',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(),
      api.properties(
          **{'$chromeos/looks_for_green': {
              'enable_looks_for_green': True
          }},
      ),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check disallow looks for green'
      ),
      api.git_footers.simulated_get_footers(
          [],
          'filter builds.check should look for green.check if CL uses Cq-Depend'
      ),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='filter builds.looks for green.find green snapshot.buildbucket.search'
      ),
      api.post_check(post_process.MustRun,
                     'filter builds.looks for green.find green snapshot'),
      api.post_process(
          post_process.LogContains, 'filter builds.looks for green',
          'cq looks log',
          ['No green snapshot found. Using latest minted snapshot.']),
      api.post_process(post_process.DropExpectation),
  )
