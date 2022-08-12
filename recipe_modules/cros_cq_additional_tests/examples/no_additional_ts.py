# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
  #setup and run tests.
  builds = api.cros_cq_additional_tests.test_api.generate_mock_build
  gerrit_change = api.cros_cq_additional_tests.test_api.generate_mock_gerrit_change
  test_plan_response = api.cros_cq_additional_tests.test_api.generate_test_plan_response
  pre_resp_str = str(test_plan_response)
  api.cros_cq_additional_tests.append_user_provided_test_suites_to_test_plan(
      builds, gerrit_change, test_plan_response)
  api.assertions.assertFalse(
      api.cros_cq_additional_tests
      .is_missing_board_build_target_footer_addtnl_ts_run())
  api.assertions.assertEqual(pre_resp_str, str(test_plan_response))


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
      api.git_footers.simulated_get_footers([],
                                            'process additional test suites',
                                            1),
  )
