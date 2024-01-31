# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_cq_additional_tests',
    'git_footers',
    'test_util',
]



def RunSteps(api):
  # Test data.
  build_1 = api.test_util.test_api.test_child_build(
      build_target_name='target1', builder_name='target1-env').message
  build_2 = api.test_util.test_api.test_child_build(build_target_name='target2',
                                                    builder_name='target2-env',
                                                    critical='NO').message
  build_3 = api.test_util.test_api.test_child_build(
      build_target_name='target3', builder_name='target3-env').message
  builds = [
      build_1,
      build_2,
      build_3,
  ]

  get_additional_test_builders = api.cros_cq_additional_tests.get_additional_test_builders(
      builds, api.buildbucket.build.input.gerrit_changes)
  api.assertions.assertCountEqual(
      get_additional_test_builders,
      api.properties['expected_get_additional_test_builders'])


def GenTests(api):

  yield api.test(
      'basic', api.buildbucket.try_build(builder='cq-orchestrator'),
      api.properties(
          **{
              '$chromeos/cros_cq_additional_tests': {
                  'enable_running_additional_tests': True,
                  'run_additional_tests_as_critical': False,
              }
          }),
      api.git_footers.simulated_get_footers(
          ['target1', 'target|target2', 'target4'],
          'get additional testable builders', 2),
      api.properties(
          expected_get_additional_test_builders=['target1-env', 'target2-env']),
      api.post_process(post_process.DropExpectation))

  yield api.test('not-enabled',
                 api.buildbucket.try_build(builder='cq-orchestrator'),
                 api.properties(expected_get_additional_test_builders=[]),
                 api.post_process(post_process.DropExpectation))
