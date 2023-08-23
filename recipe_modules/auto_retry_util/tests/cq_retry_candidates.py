# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import typing

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_infra_config',
    'gerrit',
    'git_footers',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):

  builds = api.auto_retry_util.cq_retry_candidates()
  build_ids = [b.id for b in builds]
  expected_build_ids = api.properties['expected_build_ids']
  api.assertions.assertCountEqual(expected_build_ids, build_ids)


def GenTests(api):

  def _elegible_gerrit_fetch_changes_response(
      changes: typing.List[common_pb2.GerritChange]) -> typing.Dict:
    return {
        c.change: {
            'change_number': c.change,
            'submittable': True
        } for c in changes
    }


  # Test changes eligible for retry.
  gerrit_changes = [
      common_pb2.GerritChange(change=123456,
                              host='chromium-review.googlesource.com',
                              patchset=7)
  ]

  eligible_value_dict = _elegible_gerrit_fetch_changes_response(gerrit_changes)

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
  failure_1_fetch_changes_response = _elegible_gerrit_fetch_changes_response(
      failure_1_changes)
  failure_2_changes = gerrit_changes + [host_2_cl_ps_1]
  failure_2_fetch_changes_response = _elegible_gerrit_fetch_changes_response(
      failure_2_changes)
  builds = [failure_1, failure_2]
  yield api.test(
      'get-latest-from-cq-group-does-not-group-same-change-number-on-different-host',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', failure_1_changes,
          failure_1_fetch_changes_response),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', failure_2_changes,
          failure_2_fetch_changes_response, iteration=2),
      api.properties(expected_build_ids=[1, 2]),
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
  fetch_changes_response = _elegible_gerrit_fetch_changes_response(changes)
  yield api.test(
      'get-latest-from-cq-group-correctly-groups-same-cls-in-different-order',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', changes,
          fetch_changes_response),
      api.properties(expected_build_ids=[2]),
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
  fetch_changes_response = _elegible_gerrit_fetch_changes_response(changes)
  builds = [failure_1, failure_2]

  yield api.test(
      'get-latest-from-cq-group-correctly-groups-same-cls-across-patchset-revisions',
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', changes,
          fetch_changes_response),
      api.properties(expected_build_ids=[2]),
      api.post_process(post_process.DropExpectation),
  )

  # Group with a failed run as the "current".
  group_1_cl = common_pb2.GerritChange(host='chromium-review',
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
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict),
      api.properties(expected_build_ids=[12]),
      api.post_process(post_process.DropExpectation),
  )

  group_2_cl = common_pb2.GerritChange(host='chromium-review',
                                       project='project', change=2, patchset=1)
  # Group with a non-retryable run as the "current".
  failure = api.test_util.test_orchestrator(
      build_id=21,
      cq=True,
      extra_changes=[group_2_cl],
      status='FAILURE',
      create_time=21,
      output_properties={
          'has_child_failures': True
      },
  ).message
  success = api.test_util.test_orchestrator(
      build_id=22,
      cq=True,
      extra_changes=[group_2_cl],
      status='SUCCESS',
      create_time=22,
  ).message
  group_2_builds = [success, failure]

  yield api.test(
      'get-latest-from-cq-group-latest-does-not-have-retryable-status',
      api.buildbucket.simulated_search_results(
          group_2_builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[]),
      api.post_process(post_process.DropExpectation),
  )

  # Group with a multiple retryable builds. Takes the latest.
  group_3_cl = common_pb2.GerritChange(host='chromium-review',
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
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict),
      api.properties(expected_build_ids=[33]),
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
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict, 2),
      api.properties(expected_build_ids=[12, 33]),
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
  yield api.test(
      'opt-out-via-footer',
      api.properties(expected_build_ids=[]),
      api.buildbucket.simulated_search_results(
          builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.git_footers.simulated_get_footers(
          ['None'], 'find candidates.filter out opt-out runs'),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out opt-out runs',
          'filtered out 1 run(s)',
      ),
      api.post_process(post_process.DropExpectation),
  )

  # The latest build for the CQ group, otherwise retriable, was us, and is
  # therefore excluded.
  failure_4 = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      tags={
          'cq_triggerer':
              'chromeos-auto-retry@chromeos-bot.iam.gserviceaccount.com',
      },
      status='FAILURE',
      create_time=12,
      output_properties={
          'has_child_failures': True
      },
  ).message
  group_4_builds = [failure_4]

  yield api.test(
      'get-latest-from-cq-group-latest-has-retryable-status-but-was-us',
      api.buildbucket.simulated_search_results(
          group_4_builds,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[]),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out runs last triggered by retry',
          'filtered out 1 run(s)',
      ),
      api.post_process(post_process.DropExpectation),
  )

  failure_with_allowlisted_experiment = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      extra_changes=[common_pb2.GerritChange(change=1, host='host')],
      status='FAILURE',
      create_time=12,
      output_properties={
          'has_child_failures': True
      },
      experiments=['auto-retry-fishfood'],
  ).message
  failure_without_allowlisted_experiment = api.test_util.test_orchestrator(
      build_id=13,
      cq=True,
      extra_changes=[common_pb2.GerritChange(change=2, host='host')],
      status='FAILURE',
      create_time=12,
      output_properties={
          'has_child_failures': True
      },
      experiments=['some-other-experiment'],
  ).message

  yield api.test(
      'filter-by-experiment-allowlist',
      api.properties(
          **{
              '$chromeos/auto_retry_util': {
                  'experiment_allowlist': ['auto-retry-fishfood']
              }
          }),
      api.buildbucket.simulated_search_results([
          failure_with_allowlisted_experiment,
          failure_without_allowlisted_experiment
      ], 'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter by experiment allowlist',
          'filtered out 1 run(s)',
      ),
      api.properties(expected_build_ids=[12]),
      api.post_process(post_process.DropExpectation),
  )

  # Basic eligibility tests.
  non_new_value_dict = {
      123456: {
          'change_number': 123456,
          'status': 'ABANDONED'
      }
  }

  non_submittable_value_dict = {
      123456: {
          'change_number': 123456,
          'submittable': False
      }
  }
  wip_value_dict = {
      123456: {
          'change_number': 123456,
          'submittable': True,
          'work_in_progress': True
      }
  }

  non_latest_value_dict = {
      123456: {
          'change_number': 123456,
          'submittable': True,
          'current_revision': 'f000' * 10,
          'patch_set_revision': 'c111' * 10
      }
  }

  builds_basic = [
      api.test_util.test_orchestrator(
          build_id=10 + i,
          cq=True,
          extra_changes=[
              common_pb2.GerritChange(host='host', project='project', change=i)
          ],
          status='FAILURE',
          create_time=10 + i,
          output_properties={
              'has_child_failures': True
          },
      ).message for i in range(1, 7)
  ]

  yield api.test(
      'filter-out-by-basic-eligibility',
      api.buildbucket.simulated_search_results(
          builds_basic,
          'find candidates.query for cq-orchestrators.buildbucket.search'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict, 1),
      api.gerrit.simulated_changes_are_submittable(
          submittable=False,
          step_name_prefix='find candidates.filter out merge conflicts'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          non_new_value_dict, 2),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          non_submittable_value_dict, 3),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          wip_value_dict, 4),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          non_latest_value_dict, 5),
      api.gerrit.set_gerrit_fetch_changes_response(
          'find candidates.filter out by basic eligibility', gerrit_changes,
          eligible_value_dict, 6),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out merge conflicts',
          'filtered out 1 run(s)',
      ),
      api.post_check(post_process.LogContains,
                     'find candidates.filter out merge conflicts',
                     'non_mergeable', ['16']),
      api.post_process(
          post_process.StepTextEquals,
          'find candidates.filter out by basic eligibility',
          'filtered out 4 run(s)',
      ),
      api.post_check(post_process.LogContains,
                     'find candidates.filter out by basic eligibility',
                     'non_new', ['15']),
      api.post_check(post_process.LogContains,
                     'find candidates.filter out by basic eligibility',
                     'non_submittable', ['14']),
      api.post_check(post_process.LogContains,
                     'find candidates.filter out by basic eligibility', 'wip',
                     ['13']),
      api.post_check(post_process.LogContains,
                     'find candidates.filter out by basic eligibility',
                     'non_latest_patch_set', ['12']),
      api.properties(expected_build_ids=[11]),
      api.post_process(post_process.DropExpectation),
  )
