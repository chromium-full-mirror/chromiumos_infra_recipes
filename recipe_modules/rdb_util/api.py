# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re

from recipe_engine import recipe_api
from PB.go.chromium.org.luci.analysis.proto.v1.common import Variant


class RDBUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with ResultDB."""

  @staticmethod
  def get_suite(composite_name: str) -> str:
    """Get the name of the suite from the composite name.

    Args:
      composite_name: Composite name of the builder.
        eg: 'betty-cq.tast_vm.tast_vm_default_shard_5_of_5', 'zork-cq.hw.bvt-inline',

    Returns:
      A string of just the suite name registered in RDB.
    """
    suite = composite_name.split('.')[-1]
    # Remove any _shard_.* suffix.
    match = re.match(r'(\w+)_shard_.*', suite)
    return match.groups()[0] if match else suite

  @staticmethod
  def get_shardless_test_config(test_config: str) -> str:
    """Get the test config without shard suffix.

    Args:
      test_config: Full test config name with the shard info.
        eg: 'betty-cq.tast_vm.tast_vm_default_shard_5_of_5'

    Returns:
      A string of just the test config name registered in RDB without the shard info.
    """
    match = re.match(r'(\w.+)_shard_.*', test_config)
    return match.groups()[0] if match else test_config

  @staticmethod
  def get_build_target_from_variant(variant: Variant) -> str:
    """Get build_target info from Variant definition.

    Args:
      variant: Variant definition of the test.

    Returns: build_target of the test or ''.
    """
    variant_map = getattr(variant, 'def')
    return variant_map.get('build_target', '')

  @staticmethod
  def get_board_from_variant(variant: Variant) -> str:
    """Get build_target info from Variant definition.

    Args:
      variant: Variant definition of the test.

    Returns: build_target of the test or ''.
    """
    variant_map = getattr(variant, 'def')
    return variant_map.get('board', '')
