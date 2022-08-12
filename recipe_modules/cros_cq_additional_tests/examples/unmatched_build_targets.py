# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'cros_cq_additional_tests',
    'gitiles',
    'repo',
    'git_footers',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  builds = api.cros_cq_additional_tests.test_api.generate_mock_build
  gerrit_change = (
      api.cros_cq_additional_tests.test_api.generate_mock_gerrit_change)
  test_plan_response = (
      api.cros_cq_additional_tests.test_api.generate_test_plan_response)
  api.cros_cq_additional_tests.append_user_provided_test_suites_to_test_plan(
      builds, gerrit_change, test_plan_response)

  api.assertions.assertTrue(
      'missing_build_traget' in
      api.cros_cq_additional_tests.unmatched_build_targets_addtnl_ts_run())
  api.assertions.assertFalse(
      api.cros_cq_additional_tests
      .is_missing_board_build_target_footer_addtnl_ts_run())


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_cq_additional_tests': {
                  'enable_running_additional_tests': True,
                  'run_additional_tests_as_critical': True,
              }
          }),
      api.git_footers.simulated_get_footers(['AddtnlTestSuite'],
                                            'process additional test suites',
                                            1),
      api.git_footers.simulated_get_footers(['missing_build_traget'],
                                            'process additional test suites',
                                            2),
      api.post_check(
          post_process.StepTextEquals, 'process additional test suites',
          ('Additional TestSuite cannot be run on build targets that are not'
           ' built or failed building as part of cq: missing_build_traget')))
