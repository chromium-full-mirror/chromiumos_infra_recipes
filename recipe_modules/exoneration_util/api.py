# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import defaultdict
from typing import List, Tuple
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import \
    TestVariantFailureRateAnalysis
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.recipe_modules.chromeos.exonerate.exonerate import OverallTestStats

RPC_BATCH_SIZE = 100


class ExonerationUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with exoneration."""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._enablement_repos = properties.enablement_repos

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

  def override_calculation(
      self, test_stats: List[FailedTestStats], overall_limit: int,
      per_target_limit: int) -> OverallTestStats.OverrideInfo:
    """Populate and return OverrideInfo based on stats of auto exoneration.

    Args:
      test_stats: List of failed tests stats.
      overall_limit: Number of auto exonerations should not exceed this limit.
      per_target_limit: Number of auto exonerations per target should not exceed this limit.

    Returns: OverrideInfo based on auto exoneration statistics.
    """
    overall_limit_exceeded = self.check_overall_limit(
        test_stats=test_stats, overall_limit=overall_limit)
    per_target_limit_exceeded, bad_target = self.check_per_target_limit(
        test_stats=test_stats, per_target_limit=per_target_limit)
    override_info = OverallTestStats.OverrideInfo()
    if overall_limit_exceeded:
      override_info.override_reason = OverallTestStats.TOO_MANY_TESTS_EXONERATED_TOTAL
    elif per_target_limit_exceeded:
      override_info.override_reason = OverallTestStats.TOO_MANY_TESTS_EXONERATED_PER_TARGET
      override_info.build_target = bad_target

    return override_info

  def check_per_target_limit(self, test_stats: List[FailedTestStats],
                             per_target_limit: int) -> Tuple[bool, str]:
    """Check if automated exoneration exceeded per target limit.

    Args:
      test_stats: List of failed tests stats.
      per_target_limit: Number of auto exonerations per target should not exceed this limit.

    Returns:
      Tuple of boolean indicating if per-target exonerations have exceeded per_target_limit
      and offending build_target. If multiple targets have exceeded, return any one.
    """
    per_target_count = defaultdict(int)
    for failed_test in test_stats:
      per_target_count[
          failed_test.build_target] += failed_test.automatically_exonerated

    for target, count in per_target_count.items():
      if count > per_target_limit:
        return True, target

    return False, ''

  def check_overall_limit(self, test_stats: List[FailedTestStats],
                          overall_limit: int) -> bool:
    """Check if automated exoneration exceeded overall limit.

    Args:
      test_stats: List of failed tests stats.
      overall_limit: Number of auto exonerations should not exceed this limit.

    Returns:
      Boolean indicating if number of exonerations has exceeded overall_limit.
    """
    overall_count = 0
    for failed_test in test_stats:
      overall_count += failed_test.automatically_exonerated

    return overall_count > overall_limit

  def get_updated_configs(self, test_stats: List[FailedTestStats],
                          manual_configs: dict) -> dict:
    """Update exoneration configs dict based on autoex analysis.

    Args:
      test_stats: List of failed tests stats.
      manual_configs: Configs for manual exoneration in the format of test_name -> [list of build_targets]

    Returns:
      A map of the same format as manual_configs but is updated to include autoex tests.
    """
    updated_configs = manual_configs
    for failed_test in test_stats:
      if failed_test.automatically_exonerated and not failed_test.manually_exonerated:
        if failed_test.test_id in updated_configs:
          updated_configs[failed_test.test_id].append(failed_test.build_target)
        else:
          updated_configs[failed_test.test_id] = [failed_test.build_target]

    return updated_configs
