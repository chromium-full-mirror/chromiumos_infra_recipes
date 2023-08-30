# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.common import GerritChange
from recipe_engine import post_process

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
  # Test changes eligible for retry.
  gerrit_changes = [
      GerritChange(change=123456, host='chromium-review.googlesource.com',
                   patchset=7)
  ]

  eligible_value_dict = {123456: {'change_number': 123456, 'submittable': True}}

  # Group with a failed run as the "current".
  success = api.test_util.test_orchestrator(
      build_id=11,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_1'
      },
      status='SUCCESS',
      create_time=11,
  ).message
  failure = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_1'
      },
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

  # Group with a non-retryable run as the "current".
  failure = api.test_util.test_orchestrator(
      build_id=21,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_2'
      },
      status='FAILURE',
      create_time=21,
      output_properties={
          'has_child_failures': True
      },
  ).message
  success = api.test_util.test_orchestrator(
      build_id=22,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_2'
      },
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
  failure_1 = api.test_util.test_orchestrator(
      build_id=31,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_3'
      },
      status='FAILURE',
      create_time=31,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_2 = api.test_util.test_orchestrator(
      build_id=32,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_3'
      },
      status='FAILURE',
      create_time=32,
      output_properties={
          'has_child_failures': True
      },
  ).message
  failure_3 = api.test_util.test_orchestrator(
      build_id=33,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_3'
      },
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
          tags={
              'cq_cl_group_key': 'group1'
          },
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
      api.post_process(post_process.DropExpectation),
  )

  # The build is retryable, but has opted out via footer.
  builds = [
      api.test_util.test_orchestrator(
          build_id=13,
          cq=True,
          tags={
              'cq_cl_group_key': 'group1'
          },
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
      api.post_process(post_process.DropExpectation),
  )

  # The latest build for the CQ group, otherwise retriable, was us, and is
  # therefore excluded.
  failure_4 = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      tags={
          'cq_cl_group_key':
              'group_1',
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
      api.post_process(post_process.DropExpectation),
  )

  failure_with_allowlisted_experiment = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_1'
      },
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
      tags={
          'cq_cl_group_key': 'group_2'
      },
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
          tags={
              'cq_cl_group_key': f'group{i}'
          },
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
          step_name_prefix='find candidates.filter out by merge conflicts'),
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
      api.properties(expected_build_ids=[11]),
      api.post_process(post_process.DropExpectation),
  )
