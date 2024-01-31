# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

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



def RunSteps(api):
  #setup test data
  builds = api.cros_cq_additional_tests.test_api.generate_mock_build
  gerrit_change = api.cros_cq_additional_tests.test_api.generate_mock_gerrit_change
  test_plan_response = api.cros_cq_additional_tests.test_api.generate_test_plan_response

  #invoke logic
  api.cros_cq_additional_tests.append_user_provided_test_suites_to_test_plan(
      builds, gerrit_change, test_plan_response)

  #check additional testsuite is added to the test plan - this is for a board/build target that is new.
  add_ts_for_bt_not_in_test_response = api.cros_cq_additional_tests.test_api.generate_mock_test_suite(
      test_suite='AddtnlTestSuite', board='mybuild', build_target='mybuild',
      pool='cellular', critical=True)

  build_target_tests = [
      test for test in test_plan_response.hw_test_units
      if test.common.build_target.name == 'mybuild'
  ]
  api.assertions.assertEqual(len(build_target_tests), 1)

  api.assertions.assertEqual(
      str(build_target_tests[0]), str(add_ts_for_bt_not_in_test_response))


def GenTests(api):

  def build_bucket_setup(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    return api.buildbucket.try_build(project='chromeos', **kwargs)

  yield api.test(
      'basic', build_bucket_setup(),
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
      api.git_footers.simulated_get_footers(['mybuild'],
                                            'process additional test suites',
                                            2),
      api.git_footers.simulated_get_footers(['cellular'],
                                            'process additional test suites',
                                            3),
      api.post_check(post_process.StepTextEquals,
                     'process additional test suites',
                     'Additional TestSuite added to test plan'))
