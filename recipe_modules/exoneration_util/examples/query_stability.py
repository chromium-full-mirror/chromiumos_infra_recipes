# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit test query_stability API"""
from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
  TestStabilityCriteria, TestVariantStabilityAnalysis
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/luci_analysis',
    'recipe_engine/raw_io',
    'exoneration_util',
]



def RunSteps(api):
  stability, criteria = api.exoneration_util.query_stability([])
  api.assertions.assertEqual(stability, [])
  api.assertions.assertEqual(criteria, None)

  stability, criteria = api.exoneration_util.query_stability(
      [], fake_data=([TestVariantStabilityAnalysis()], TestStabilityCriteria()))
  api.assertions.assertEqual(stability, [TestVariantStabilityAnalysis()])
  api.assertions.assertEqual(criteria, TestStabilityCriteria())

  def_map = {'build_target': 'bt', 'board': 'board'}
  test_variant = {'testId': 'test_name', 'variant': {'def': def_map}}
  stability, criteria = api.exoneration_util.query_stability([test_variant] *
                                                             120)


def GenTests(api):

  def get_rpc_response_data():
    """Mock RPC call data"""
    output = api.luci_analysis.query_stability_example_output()
    return api.json.dumps(output)

  yield api.test(
      'basic',
      # Check that LUCI Analysis gets called twice on 120 input size.
      api.step_data(
          'query LUCI Analysis for stability.rpc call',
          stdout=api.raw_io.output_text(get_rpc_response_data()),
      ),
      api.step_data(
          'query LUCI Analysis for stability (2).rpc call',
          stdout=api.raw_io.output_text(get_rpc_response_data()),
      ),
      # This post_check is redundant as recipe will raise error for providing
      # mocking data for non-existent steps
      api.post_check(post_process.MustRun,
                     'query LUCI Analysis for stability (2).rpc call'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'step_failure',
      # Failure in any batch will fail the whole API. The second RPC call
      # will result in failure due to lack of mock data.
      api.step_data(
          'query LUCI Analysis for stability.rpc call',
          stdout=api.raw_io.output_text(get_rpc_response_data()),
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE')
