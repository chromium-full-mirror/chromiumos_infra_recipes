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
  builds = api.cros_cq_additional_tests.test_api.generate_mock_build
  gerrit_change = (
      api.cros_cq_additional_tests.test_api.generate_mock_gerrit_change)
  test_plan_response = (
      api.cros_cq_additional_tests.test_api.generate_test_plan_response)

  try:
    api.cros_cq_additional_tests.append_user_provided_test_suites_to_test_plan(
        builds, gerrit_change, test_plan_response)
  except api.cros_cq_additional_tests.CrosCqAddnlTestsMissingBuildTargetsError as e:
    api.assertions.assertTrue('missing_build_target' in [
        t.common.display_name.split('.hw', 1)[0]
        for t in e.not_runnable_addtnl_tests
    ])


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
      api.git_footers.simulated_get_footers(['missing_build_target'],
                                            'process additional test suites',
                                            2),
      api.post_check(
          post_process.StepTextEquals, 'process additional test suites',
          ('Additional TestSuites cannot be run on build targets that are not'
           ' built or failed building as part of cq: missing_build_target')))
