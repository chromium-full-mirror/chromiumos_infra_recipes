# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for testing with cros_tags."""
from recipe_engine import recipe_test_api


class CrosTagsTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing with cros_tags."""

  def tags(self, **tags):
    """Helper for generating a list of StringPair messages.

    Args:
      tags (dict): Dict mapping keys to values.  If the value is a list,
          multiple tags for the same key will be created.

    Returns:
      (list[StringPair]) tags.
    """
    return self.m.buildbucket.tags(**tags)
