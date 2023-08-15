# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_infra_config',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):

  # pylint: disable=protected-access
  builds = api.auto_retry_util._get_current_cq_orchs_with_retryable_statuses()
  build_ids = [b.id for b in builds]
  expected_build_ids = api.properties['expected_build_ids']
  api.assertions.assertCountEqual(build_ids, expected_build_ids)


def GenTests(api):

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
  ).message
  group_1_builds = [success, failure]

  yield api.test(
      'latest-has-retryable-status',
      api.buildbucket.simulated_search_results(
          group_1_builds, 'query for cq-orchestrators.buildbucket.search'),
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
      'latest-does-not-have-retryable-status',
      api.buildbucket.simulated_search_results(
          group_2_builds, 'query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[]),
      api.post_process(post_process.DropExpectation),
  )

  # Group with a non-retryable run as the "current".
  failure_1 = api.test_util.test_orchestrator(
      build_id=31,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_3'
      },
      status='FAILURE',
      create_time=31,
  ).message
  failure_2 = api.test_util.test_orchestrator(
      build_id=32,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_3'
      },
      status='FAILURE',
      create_time=32,
  ).message
  failure_3 = api.test_util.test_orchestrator(
      build_id=33,
      cq=True,
      tags={
          'cq_cl_group_key': 'group_3'
      },
      status='INFRA_FAILURE',
      create_time=33,
  ).message
  group_3_builds = [failure_1, failure_2, failure_3]

  yield api.test(
      'multiple-with-retryable-status-takes-latest',
      api.buildbucket.simulated_search_results(
          group_3_builds, 'query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[33]),
      api.post_process(post_process.DropExpectation),
  )

  # Test that we do get one per group that has a current cq-orchestrator with a
  # retryable status (one from group_1 and one from group_3)
  all_group_builds = group_1_builds + group_2_builds + group_3_builds
  yield api.test(
      'multiple-cq-cl-groups',
      api.buildbucket.simulated_search_results(
          all_group_builds, 'query for cq-orchestrators.buildbucket.search'),
      api.properties(expected_build_ids=[12, 33]),
      api.post_process(post_process.DropExpectation),
  )
