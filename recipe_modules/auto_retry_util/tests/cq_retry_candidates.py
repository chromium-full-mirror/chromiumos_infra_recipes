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

  builds = api.auto_retry_util.cq_retry_candidates()
  build_ids = [b.id for b in builds]
  expected_build_ids = api.properties['expected_build_ids']
  api.assertions.assertCountEqual(expected_build_ids, build_ids)


def GenTests(api):

  # Group with a failed run as the "current".
  success = api.test_util.test_orchestrator(
      build_id=11,
      cq=True,
      tags={
          'cq_cl_group_key': 'group1'
      },
      status='SUCCESS',
      create_time=11,
  ).message
  failure = api.test_util.test_orchestrator(
      build_id=12,
      cq=True,
      tags={
          'cq_cl_group_key': 'group1'
      },
      status='FAILURE',
      create_time=12,
      output_properties={
          'has_child_failures': True
      },
  ).message
  group_1_builds = [success, failure]

  yield api.test(
      'get-latest-from-cq-group',
      api.properties(expected_build_ids=[12]),
      api.post_check(post_process.MustRun, 'query for cq-orchestrators'),
      api.buildbucket.simulated_search_results(
          group_1_builds, 'query for cq-orchestrators.buildbucket.search'),
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
      api.post_check(post_process.MustRun, 'query for cq-orchestrators'),
      api.buildbucket.simulated_search_results(
          builds, 'query for cq-orchestrators.buildbucket.search'),
      api.post_process(post_process.DropExpectation),
  )
