# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
    TestVariantFailureRateAnalysis

RPC_BATCH_SIZE = 100


class ExonerationUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with exoneration."""

  def query_failure_rate(
      self,
      test_variant_list: List[dict]) -> List[TestVariantFailureRateAnalysis]:
    """Query failure rate from luci_analysis.

    Args:
      test_variant_list: A list of dicts with test name and variant def to query on.

    Returns:
      List of TestVariantFailureRateAnalysis for each input.
    """
    failure_rates = []
    # Break up the input into chunks of RPC_BATCH_SIZE and query LUCI analysis.
    for i in range(0, len(test_variant_list), RPC_BATCH_SIZE):
      failure_rates.extend(
          self.m.luci_analysis.query_failure_rate(
              test_variant_list[i:i + RPC_BATCH_SIZE], project='chromeos'))

    return failure_rates
