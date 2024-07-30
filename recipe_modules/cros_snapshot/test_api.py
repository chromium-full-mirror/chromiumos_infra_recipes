# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing CrOS recipes.

This module provides helpers to make testing CrOS recipes simpler and more
consistent.
"""

from typing import Optional

from recipe_engine import recipe_test_api


class CrosSnapshotTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing cros_snapshot recipe."""

  def simulated_snapshot_identifier(self, snapshot_identifier: Optional[int],
                                    step_name=None):
    step_name = step_name if step_name else 'read snapshot identifier'
    footer_value = [] if snapshot_identifier is None else [
        str(snapshot_identifier)
    ]
    property_value = '' if snapshot_identifier is None else str(
        snapshot_identifier)
    return (self.m.properties(
        **{'$chromeos/cros_snapshot': {
            'snapshot_identifier': property_value,
        }}) + self.m.git_footers.simulated_get_footers(footer_value, step_name))
