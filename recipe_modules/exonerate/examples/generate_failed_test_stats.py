# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
    TestVariantFailureRateAnalysis
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/luci_analysis',
    'exonerate',
]



def RunSteps(api):

  # Test data
  failure_rate_1 = api.luci_analysis.test_api.generate_analysis(
      test_id='not-exonerated-test', expected_count=10)
  failure_rate_1['variant'] = {'def': {'build_target': 'target'}}
  failure_rate_2 = api.luci_analysis.test_api.generate_analysis(
      test_id='exonerated-test', unexpected_count=10)
  failure_rate_2['variant'] = {'def': {'build_target': 'target'}}
  # Test name and variant taken from the mock exoneration configs defined in
  # exonerate.test_api.fake_exoneration_configs(). This test case should be
  # manually exonerated.
  failure_rate_3 = api.luci_analysis.test_api.generate_analysis(
      test_id='camera.TakesGreatPhotos', unexpected_count=1)
  failure_rate_3['variant'] = {'def': {'build_target': 'target'}}

  failure_rates = [
      json_format.ParseDict(failure_rate_1, TestVariantFailureRateAnalysis()),
      json_format.ParseDict(failure_rate_2, TestVariantFailureRateAnalysis()),
      json_format.ParseDict(failure_rate_3, TestVariantFailureRateAnalysis()),
  ]

  expecteded_failed_test_stats = [
      FailedTestStats(test_id='not-exonerated-test', build_target='target',
                      automatically_exonerated=False),
      FailedTestStats(test_id='exonerated-test', build_target='target',
                      automatically_exonerated=True,
                      consistent_failure_count=10),
      FailedTestStats(test_id='camera.TakesGreatPhotos', build_target='target',
                      manually_exonerated=True, consistent_failure_count=1),
  ]

  failed_test_stats = api.exonerate.generate_failed_test_stats([
      json_format.ParseDict(failure_rate_1, TestVariantFailureRateAnalysis()),
      json_format.ParseDict(failure_rate_2, TestVariantFailureRateAnalysis()),
      json_format.ParseDict(failure_rate_3, TestVariantFailureRateAnalysis()),
  ])
  # Call twice to ensure configs are only loaded once.
  failed_test_stats = api.exonerate.generate_failed_test_stats(failure_rates)

  api.assertions.assertCountEqual(failed_test_stats,
                                  expecteded_failed_test_stats)


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(
          post_process.MustRun,
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto'),
      api.post_check(
          post_process.DoesNotRun,
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto (2)'
      ),
      api.post_process(post_process.DropExpectation),
  )
