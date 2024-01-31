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

  build_target_tests = [
      test for test in test_plan_response.hw_test_units
      if test.common.build_target.name == 'build_target'
  ]

  api.assertions.assertEqual(len(build_target_tests), 1)
  hw_tests = build_target_tests[0].hw_test_cfg.hw_test
  api.assertions.assertEqual(len(hw_tests), 2)
  suites = [h.suite for h in hw_tests]
  api.assertions.assertTrue('AddtnlTestSuite' in suites)
  api.assertions.assertTrue('suite' in suites)
  api.assertions.assertEqual(2, len(suites))

  add_ts = [h for h in hw_tests if h.suite == 'AddtnlTestSuite']
  api.assertions.assertFalse(add_ts[0].common.critical.value)


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
                  'run_additional_tests_as_critical': False,
              }
          }),
      api.git_footers.simulated_get_footers(['AddtnlTestSuite'],
                                            'process additional test suites',
                                            1),
      api.git_footers.simulated_get_footers(['board|build_target'],
                                            'process additional test suites',
                                            2),
      api.git_footers.simulated_get_footers(['cellular'],
                                            'process additional test suites',
                                            3),
      api.post_check(post_process.StepTextEquals,
                     'process additional test suites',
                     'Additional TestSuite added to test plan'))
