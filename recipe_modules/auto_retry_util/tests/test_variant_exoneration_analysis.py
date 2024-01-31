# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.recipe_modules.chromeos.exonerate.exonerate import OverallTestStats

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/luci_analysis',
    'recipe_engine/properties',
    'auto_retry_util',
    'test_util',
]



def RunSteps(api):
  prev_exon, new_exon, outstanding = api.auto_retry_util.test_variant_exoneration_analysis(
      api.buildbucket.build)

  prev_exon_json = [json_format.MessageToJson(x) for x in prev_exon]
  new_exon_json = [json_format.MessageToJson(x) for x in new_exon]
  outstanding_json = [json_format.MessageToJson(x) for x in outstanding]

  expected_prev_exon = api.properties['expected_prev_exon']
  expected_new_exon = api.properties['expected_new_exon']
  expected_outstanding = api.properties['expected_outstanding']

  api.assertions.assertCountEqual(prev_exon_json, expected_prev_exon)
  api.assertions.assertCountEqual(new_exon_json, expected_new_exon)
  api.assertions.assertCountEqual(outstanding_json, expected_outstanding)


def GenTests(api):

  yield api.test(
      'skip-no-output-prop',
      api.test_util.test_orchestrator(cq=True).build,
      api.properties(expected_prev_exon=[], expected_new_exon=[],
                     expected_outstanding=[]),
      api.post_check(post_process.StepTextEquals, 'exoneration analysis',
                     'skipping: no test variant failures'),
      api.post_process(post_process.DropExpectation),
  )

  failed_test_stats = OverallTestStats()
  ft = failed_test_stats.failed_tests.add()
  failed_test_stats.override_info.override_reason = (
      OverallTestStats.TOO_MANY_TESTS_EXONERATED_TOTAL)
  yield api.test(
      'skip-exon-overridden',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'failed_test_stats': json_format.MessageToDict(failed_test_stats)
          }).build,
      api.properties(expected_prev_exon=[], expected_new_exon=[],
                     expected_outstanding=[json_format.MessageToJson(ft)]),
      api.post_check(post_process.StepTextEquals, 'exoneration analysis',
                     'skipping: overridden by guardrails'),
      api.post_process(post_process.DropExpectation),
  )

  failed_test_stats = OverallTestStats()
  ft = failed_test_stats.failed_tests.add()
  ft.manually_exonerated = True
  yield api.test(
      'skip-all-prev-exonerated',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'failed_test_stats': json_format.MessageToDict(failed_test_stats)
          }).build,
      api.properties(expected_prev_exon=[json_format.MessageToJson(ft)],
                     expected_new_exon=[], expected_outstanding=[]),
      api.post_check(post_process.StepTextEquals, 'exoneration analysis',
                     'skipping: no outstanding failures'),
      api.post_process(post_process.DropExpectation),
  )

  # Original FailedTestStats
  prev_exon = FailedTestStats(test_id='prev-exon-test', build_target='target',
                              manually_exonerated=True)
  new_exon_before = FailedTestStats(test_id='new-exon-test',
                                    build_target='target',
                                    consistent_failure_count=2)
  new_exon_after = FailedTestStats(test_id='new-exon-test',
                                   build_target='target',
                                   automatically_exonerated=True,
                                   consistent_failure_count=10)

  # Test failure rates
  not_exon_failure_rate = api.luci_analysis.generate_analysis(
      test_id='not-exon-test', unexpected_count=5)
  not_exon_failure_rate['variant'] = {'def': {'build_target': 'target'}}
  new_exon_failure_rate = api.luci_analysis.generate_analysis(
      test_id='new-exon-test', unexpected_count=10)
  new_exon_failure_rate['variant'] = {'def': {'build_target': 'target'}}

  # Updated FailedTestStats
  outstanding_before = FailedTestStats(test_id='not-exon-test',
                                       build_target='target')
  outstanding_after = FailedTestStats(test_id='not-exon-test',
                                      build_target='target',
                                      consistent_failure_count=5)

  failed_test_stats = OverallTestStats(
      failed_tests=[prev_exon, new_exon_before, outstanding_before])
  yield api.test(
      'one-prev-one-new-one-outstanding',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'failed_test_stats': json_format.MessageToDict(failed_test_stats)
          }).build,
      api.properties(
          expected_prev_exon=[json_format.MessageToJson(prev_exon)],
          expected_new_exon=[json_format.MessageToJson(new_exon_after)],
          expected_outstanding=[json_format.MessageToJson(outstanding_after)]),
      api.luci_analysis.query_failure_rate_results(
          [not_exon_failure_rate, new_exon_failure_rate]),
      api.post_check(
          post_process.StepTextEquals, 'exoneration analysis',
          '1 previously exonerated, 1 newly exonerated, 1 outstanding'),
      api.post_process(post_process.DropExpectation),
  )
