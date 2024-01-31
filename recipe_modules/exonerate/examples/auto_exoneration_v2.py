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
from recipe_engine.recipe_api import Property

from RECIPE_MODULES.chromeos.exonerate.api import FailedTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/luci_analysis',
    'recipe_engine/properties',
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

  # No mock data, RPC call will raise Step Failure but dry run should not fail
  yield api.test(
      'basic',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.properties(failed_tests=failed_tests_data))

  # Empty failed tests
  yield api.test(
      'empty-failed-tests',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.properties(failed_tests=[]))

  # Success scenario with valid mock RPC response data
  yield api.test(
      'success-scenario',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.properties(failed_tests=failed_tests_data,
                     rpc_response_data=rpc_response_data))

  # Experiment not enabled
  yield api.test(
      'experiment-not-enabled',
      api.properties(failed_tests=failed_tests_data,
                     rpc_response_data=rpc_response_data))
