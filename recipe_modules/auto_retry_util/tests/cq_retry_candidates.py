# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the cq_retry_candidates function."""

import typing

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'auto_retry_util',
    'gerrit',
    'test_util',
]



def RunSteps(api):

  builds = api.auto_retry_util.cq_retry_candidates()
  build_ids = [b.id for b in builds]
  expected_build_ids = api.properties['expected_build_ids']
  api.assertions.assertCountEqual(expected_build_ids, build_ids)


def GenTests(api):

  def _eligible_gerrit_fetch_changes_response(
      changes: typing.List[common_pb2.GerritChange]) -> typing.Dict:
    return {
        c.change: {
            'change_number':
                c.change,
        } for c in changes
    }

  # Test changes eligible for retry.
  gerrit_changes = [
      common_pb2.GerritChange(change=123456,
                              host='chromium-review.googlesource.com',
                              patchset=7)
  ]

  host_1_cl_ps_1 = common_pb2.GerritChange(host='host1', project='project',
                                           change=1, patchset=1)
  host_2_cl_ps_1 = common_pb2.GerritChange(host='host2', project='project',
                                           change=1, patchset=1)
  failure_1 = api.test_util.test_orchestrator(
      build_id=1,
      cq=True,
      extra_changes=[host_1_cl_ps_1],
      status='FAILURE',
      create_time=1,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_2 = api.test_util.test_orchestrator(
      build_id=2,
      cq=True,
      extra_changes=[host_2_cl_ps_1],
      status='FAILURE',
      create_time=2,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_1_changes = gerrit_changes + [host_1_cl_ps_1]
  failure_1_fetch_changes_response = _eligible_gerrit_fetch_changes_response(
      failure_1_changes)
  failure_2_changes = gerrit_changes + [host_2_cl_ps_1]
  failure_2_fetch_changes_response = _eligible_gerrit_fetch_changes_response(
      failure_2_changes)
  builds = [failure_1, failure_2]
  yield api.test(
      'get-latest-from-cq-group-does-not-group-same-change-number-on-different-host',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', failure_2_changes,
          failure_2_fetch_changes_response,
          step_name=f'fetch changes for {failure_2.id}'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', failure_1_changes,
          failure_1_fetch_changes_response,
          step_name=f'fetch changes for {failure_1.id}'),
      api.properties(expected_build_ids=[failure_1.id, failure_2.id]),
      api.post_process(post_process.DropExpectation),
  )

  failure_1 = api.test_util.test_orchestrator(
      build_id=1,
      cq=True,
      extra_changes=[host_1_cl_ps_1, host_2_cl_ps_1],
      status='FAILURE',
      create_time=1,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_2 = api.test_util.test_orchestrator(
      build_id=2,
      cq=True,
      extra_changes=[host_2_cl_ps_1, host_1_cl_ps_1],
      status='FAILURE',
      create_time=2,
      output_properties={
          'has_child_failures': True
      },
  ).message
  builds = [failure_1, failure_2]
  changes = gerrit_changes + [host_1_cl_ps_1, host_2_cl_ps_1]
  fetch_changes_response = _eligible_gerrit_fetch_changes_response(changes)
  yield api.test(
      'get-latest-from-cq-group-correctly-groups-same-cls-in-different-order',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', changes,
          fetch_changes_response,
          step_name=f'fetch changes for {failure_2.id}'),
      api.properties(expected_build_ids=[failure_2.id]),
      api.post_process(post_process.DropExpectation),
  )

  host_1_cl_ps_2 = common_pb2.GerritChange(host='host1', project='project',
                                           change=1, patchset=2)
  host_2_cl_ps_2 = common_pb2.GerritChange(host='host2', project='project',
                                           change=1, patchset=2)
  failure_1 = api.test_util.test_orchestrator(
      build_id=1,
      cq=True,
      extra_changes=[host_1_cl_ps_1, host_2_cl_ps_1],
      status='FAILURE',
      create_time=1,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_2 = api.test_util.test_orchestrator(
      build_id=2,
      cq=True,
      extra_changes=[host_2_cl_ps_2, host_1_cl_ps_2],
      status='FAILURE',
      create_time=2,
      output_properties={
          'has_child_failures': True
      },
  ).message
  changes = gerrit_changes + [host_2_cl_ps_2, host_1_cl_ps_2]
  fetch_changes_response = _eligible_gerrit_fetch_changes_response(changes)
  builds = [failure_1, failure_2]

  yield api.test(
      'get-latest-from-cq-group-correctly-groups-same-cls-across-patchset-revisions',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', changes,
          fetch_changes_response,
          step_name=f'fetch changes for {failure_2.id}'),
      api.properties(expected_build_ids=[failure_2.id]),
      api.post_process(post_process.DropExpectation),
  )

  # Group with a failed run as the "current".
  group_1_cl = common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                       project='project', change=1, patchset=1)
  success = api.test_util.test_orchestrator(
      build_id=11,
      cq=True,
      extra_changes=[group_1_cl],
      status='SUCCESS',
      create_time=11,
  ).message
  failure = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      extra_changes=[group_1_cl],
      status='FAILURE',
      create_time=12,
      output_properties={
          'has_child_failures': True
      },
  ).message
  group_1_builds = [success, failure]
  yield api.test(
      'get-latest-from-cq-group-latest-has-retryable-status',
      api.buildbucket.simulated_search_results(
          group_1_builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', gerrit_changes,
          _eligible_gerrit_fetch_changes_response(gerrit_changes),
          step_name=f'fetch changes for {failure.id}'),
      api.properties(expected_build_ids=[failure.id]),
      api.post_process(post_process.DropExpectation),
  )

  group_2_cl = common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                       project='project', change=2, patchset=1)
  # Group with a non-retryable run as the "current".
  failure_2x = api.test_util.test_orchestrator(
      build_id=21,
      cq=True,
      extra_changes=[group_2_cl],
      status='FAILURE',
      create_time=21,
      output_properties={
          'has_child_failures': True
      },
  ).message
  success_2x = api.test_util.test_orchestrator(
      build_id=22,
      cq=True,
      extra_changes=[group_2_cl],
      status='SUCCESS',
      create_time=22,
  ).message
  group_2_builds = [success_2x, failure_2x]

  yield api.test(
      'get-latest-from-cq-group-latest-does-not-have-retryable-status',
      api.buildbucket.simulated_search_results(
          group_2_builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[]),
      api.post_process(post_process.DropExpectation),
  )

  # Group with a multiple retryable builds. Takes the latest.
  group_3_cl = common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                       project='project', change=3, patchset=1)
  failure_1 = api.test_util.test_orchestrator(
      build_id=31,
      cq=True,
      extra_changes=[group_3_cl],
      status='FAILURE',
      create_time=31,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_2 = api.test_util.test_orchestrator(
      build_id=32,
      cq=True,
      extra_changes=[group_3_cl],
      status='FAILURE',
      create_time=32,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_3 = api.test_util.test_orchestrator(
      build_id=33,
      cq=True,
      extra_changes=[group_3_cl],
      status='INFRA_FAILURE',
      create_time=33,
      output_properties={
          'has_child_failures': True
      },
  ).message
  group_3_builds = [failure_1, failure_2, failure_3]

  yield api.test(
      'get-latest-from-cq-group-multiple-with-retryable-status-takes-latest',
      api.buildbucket.simulated_search_results(
          group_3_builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', gerrit_changes,
          _eligible_gerrit_fetch_changes_response(gerrit_changes),
          step_name=f'fetch changes for {failure_3.id}'),
      api.properties(expected_build_ids=[failure_3.id]),
      api.post_process(post_process.DropExpectation),
  )

  # Test that we do get one per group that has a current cq-orchestrator with a
  # retryable status (one from group_1 and one from group_3)
  all_group_builds = group_1_builds + group_2_builds + group_3_builds
  yield api.test(
      'get-latest-from-cq-group-multiple-cq-cl-groups',
      api.buildbucket.simulated_search_results(
          all_group_builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', gerrit_changes,
          _eligible_gerrit_fetch_changes_response(gerrit_changes),
          step_name=f'fetch changes for {failure_3.id}'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', gerrit_changes,
          _eligible_gerrit_fetch_changes_response(gerrit_changes),
          step_name=f'fetch changes for {failure.id}'),
      api.properties(expected_build_ids=[failure.id, failure_3.id]),
      api.post_process(post_process.DropExpectation),
  )

  # The latest build for the CQ group does not have a retryable failure mode.
  builds = [
      api.test_util.test_orchestrator(
          build_id=13,
          cq=True,
          status='FAILURE',
          create_time=13,
          output_properties={
              'has_child_failures': False
          },
      ).message
  ]
  yield api.test(
      'filter-out-non-retryable-failure-mode',
      api.properties(expected_build_ids=[]),
      api.post_check(post_process.MustRun,
                     'find candidates.query for cq-orchestrators'),
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out unsupported failure modes',
          'filtered out 1 run(s)',
      ),
      api.post_process(post_process.DropExpectation),
  )

  # The build is retryable, but has opted out via footer.
  builds = [
      api.test_util.test_orchestrator(
          build_id=13,
          cq=True,
          status='FAILURE',
          create_time=13,
          output_properties={
              'has_child_failures': True
          },
      ).message
  ]

  # The build is retryable, but could not fetch all the CLs.
  yield api.test(
      'failed-to-fetch-gerrit-changes',
      api.properties(expected_build_ids=[]),
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.override_step_data(
          f'find candidates.filter out closed CLs.fetch changes for {builds[0].id}',
          stdout=api.json.output({'changes': [{}]})),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out closed CLs',
          'filtered out 1 run(s)',
      ),
      api.post_process(
          post_process.PropertyEquals, 'filtered_build_stats', {
              'failed_gerrit_fetch': 1,
              'non_new': 0,
              'total_with_retryable_statuses': 1,
              'unsupported_failure_mode': 0,
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'filter-out-non-new',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', gerrit_changes,
          {123456: {
              'change_number': 123456,
              'status': 'ABANDONED'
          }}, step_name=f'fetch changes for {builds[0].id}'),
      api.post_process(
          post_process.PropertyEquals, 'filtered_build_stats', {
              'failed_gerrit_fetch': 0,
              'non_new': 1,
              'total_with_retryable_statuses': 1,
              'unsupported_failure_mode': 0,
          }),
      api.properties(expected_build_ids=[]),
      api.post_process(post_process.DropExpectation),
  )

  # Test cq-orchestrator that had an infra failure.
  builds = [
      api.test_util.test_orchestrator(
          build_id=13,
          cq=True,
          status='INFRA_FAILURE',
          create_time=13,
          output_properties={
              'has_child_failures': False
          },
          experiments=['chromeos.auto_retry_util.retry_infra_failures'],
      ).message
  ]
  yield api.test(
      'infra-failure-experimental-feature-enabled',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES,
                          experiment_flag='chromeos.auto_retry_util.retry_infra_failures'
                      )
                  ])
          }),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out closed CLs', gerrit_changes,
          _eligible_gerrit_fetch_changes_response(gerrit_changes),
          step_name=f'fetch changes for {builds[0].id}'),
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[builds[0].id]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'infra-failure-experimental-feature-not-enabled',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES,
                          experiment_flag='other-experiment-name')
                  ])
          }),
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out unsupported failure modes',
          'filtered out 1 run(s)',
      ),
      api.properties(expected_build_ids=[]),
      api.post_process(post_process.DropExpectation),
  )
