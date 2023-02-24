# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re

from recipe_engine import recipe_api


class RDBUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with ResultDB."""

  def get_vm_suite(self, composite_name: str) -> str:
    """Get the name of the suite of a VM/GCE run from the composite name.

    Args:
      composite_name: Composite name of the builder.
        eg: 'betty-cq.tast_vm.tast_vm_default_shard_5_of_5'

    Returns:
      A string of just the suite name registered in RDB.
    """
    suite = composite_name.split('.')[-1]
    # Remove any _shard_.* suffix.
    match = re.match(r'(\w+)_shard_.*', suite)
    return match.groups()[0] if match else suite
