# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from RECIPE_MODULES.chromeos.cros_history.api import PASSED_TESTS_KEY

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_history',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  success, retryable, outstanding = api.auto_retry_util.analyze_test_results(
      api.buildbucket.build)
  expected_success = api.properties['expected_success']
  expected_retryable = api.properties['expected_retryable']
  expected_outstanding = api.properties['expected_outstanding']
  api.assertions.assertCountEqual(success, expected_success)
  api.assertions.assertCountEqual(retryable, expected_retryable)
  api.assertions.assertCountEqual(outstanding, expected_outstanding)


def GenTests(api):

  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'cq-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1'
  orch.orchestrator.child_specs.add().name = 'builder2'
  builder1 = configs.builder_configs.add()
  builder1.id.name = 'builder1'
  builder2 = configs.builder_configs.add()
  builder2.id.name = 'builder2'

  test_summary = [
      {
          'builder_name': 'builder1',
          'status': 'SUCCESS',
          'critical': True,
          'name': 'builder1.hw.suite'
      },
      {
          'builder_name': 'builder2',
          'status': 'FAILURE',
          'critical': True,
          'name': 'builder2.tast_vm.suite',
          'revision': 'fake-revision',
      },
      # Non-critical counts as success.
      {
          'builder_name': 'builder2',
          'status': 'FAILURE',
          'critical': False,
          'name': 'builder2.tast_vm.non_crit_suite'
      },
      # Builder no longer a CQ verifier.
      {
          'builder_name': 'builder3',
          'status': 'FAILURE',
          'critical': True,
          'name': 'builder3.tast_gce.suite'
      },
  ]
  yield api.test(
      'removed-verifier',
      api.test_util.test_orchestrator(output_properties={
          'test_summary': test_summary
      }).build,
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_uprev_response(end_time=0)
      ], step_name='analyzing test results.check if build is broken.buildbucket.search'
                                                               ),
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_uprev_response(end_time=3)
      ], step_name='analyzing test results.check if build is broken.buildbucket.search (2)'
                                                               ),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=[
              'builder1.hw.suite', 'builder2.tast_vm.non_crit_suite'
          ], expected_retryable=['builder3.tast_gce.suite'],
          expected_outstanding=['builder2.tast_vm.suite']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'broken-until-updated',
      api.test_util.test_orchestrator(output_properties={
          'test_summary': test_summary
      }).build,
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_uprev_response(end_time=3)
      ], step_name='analyzing test results.check if build is broken.buildbucket.search'
                                                               ),
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_uprev_response(end_time=0)
      ], step_name='analyzing test results.check if build is broken.buildbucket.search (2)'
                                                               ),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=[
              'builder1.hw.suite', 'builder2.tast_vm.non_crit_suite'
          ], expected_retryable=[
              'builder2.tast_vm.suite', 'builder3.tast_gce.suite'
          ], expected_outstanding=[]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'previously-exonerated',
      api.test_util.test_orchestrator(
          output_properties={
              'test_summary':
                  test_summary,
              PASSED_TESTS_KEY: [
                  'builder1.hw.suite', 'builder2.tast_vm.non_crit_suite',
                  'builder2.tast_vm.suite'
              ]
          }).build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=[
              'builder1.hw.suite',
              'builder2.tast_vm.non_crit_suite',
              'builder2.tast_vm.suite',
          ], expected_retryable=['builder3.tast_gce.suite'],
          expected_outstanding=[]),
      api.post_process(post_process.DropExpectation),
  )
