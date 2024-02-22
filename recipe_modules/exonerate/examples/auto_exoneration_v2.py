# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit test auto exoneration v2 (dry run) logic."""

from google.protobuf import json_format

from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
  TestStabilityCriteria
from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
  TestVariantStabilityAnalysis
from PB.go.chromium.org.luci.resultdb.proto.v1.resultdb import \
  QueryTestVariantsResponse
from recipe_engine.recipe_api import Property

from RECIPE_MODULES.chromeos.exonerate.api import FailedTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/luci_analysis',
    'recipe_engine/properties',
    'recipe_engine/resultdb',
    'exonerate',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'failed_tests': Property(kind=list, default=None),
    'rpc_response_data': Property(kind=dict, default=None),
}


def RunSteps(api, failed_tests, rpc_response_data):
  fake_data = None
  if rpc_response_data:
    stability = [
        json_format.ParseDict(
            rpc_response_data.get('testVariants')[0],
            TestVariantStabilityAnalysis(), ignore_unknown_fields=True)
    ]
    criteria = json_format.ParseDict(
        rpc_response_data.get('criteria'), TestStabilityCriteria(),
        ignore_unknown_fields=True)
    fake_data = (stability, criteria)
  api.exonerate.auto_exoneration_analysis_v2(failed_tests=failed_tests,
                                             fake_data=fake_data)


def GenTests(api):
  failed_tests_data = [
      FailedTest(name='tast.lockscreen.CloseLid.fieldtrial_testing_config_on',
                 board='hana', build_target='hana', model='')
  ]
  rpc_response_data = api.luci_analysis.query_stability_example_output()
  test_variants_data = json_format.Parse(text=query_test_variants_response_json,
                                         message=QueryTestVariantsResponse(),
                                         ignore_unknown_fields=True)

  # No mock data, RPC call will raise Step Failure but dry run should not fail
  yield api.test(
      'basic',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.resultdb.query_test_variants(
          QueryTestVariantsResponse(),
          step_name='Auto exoneration v2 dry run.query_test_variants'),
      api.properties(failed_tests=failed_tests_data))

  # Empty failed tests
  yield api.test(
      'empty-failed-tests',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.resultdb.query_test_variants(
          QueryTestVariantsResponse(),
          step_name='Auto exoneration v2 dry run.query_test_variants'),
      api.properties(failed_tests=[]))

  # Success scenario with valid mock RPC response data
  yield api.test(
      'success-scenario',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.resultdb.query_test_variants(
          test_variants_data,
          step_name='Auto exoneration v2 dry run.query_test_variants'),
      api.properties(failed_tests=failed_tests_data,
                     rpc_response_data=rpc_response_data))

  # Not setting resultdb.query_test_variants mock data will raise an exception
  yield api.test(
      'failure-scenario-exception',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.properties(failed_tests=failed_tests_data,
                     rpc_response_data=rpc_response_data))

  # Experiment not enabled
  yield api.test(
      'experiment-not-enabled',
      api.properties(failed_tests=failed_tests_data,
                     rpc_response_data=rpc_response_data))


query_test_variants_response_json = '''{
    "testVariants": [
        {
            "testId": "tast.lockscreen.CloseLid.fieldtrial_testing_config_on",
            "variant": {
                "def": {
                    "build_target": "hana",
                    "board": "hana"
                }
            },
            "status": "UNEXPECTED",
            "sourcesId": "aaaa"
        }
    ],
    "sources": {
        "aaaa": {
            "gitilesCommit": {
                "host": "chrome-internal.googlesource.com",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot",
                "commitHash": "93cf925c8cd052ebbe6133a8cef885d92c56cdc5",
                "position": "92279"
            }
        }
    }
}'''
