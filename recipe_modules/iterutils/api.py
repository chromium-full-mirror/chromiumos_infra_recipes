# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class IterutilsApi(recipe_api.RecipeApi):
  """Utility functions for working with iterables"""

  def get_one(self, iterable, predicate, error_msg):
    """Returns the one item from iterable matching predicate.

      Raises:
        A ValueError with error_msg if iterable doesn't have exactly one item
        matching predicate.
    """
    matching = [x for x in iterable if predicate(x)]
    if len(matching) != 1:
      raise ValueError(error_msg)

    return matching[0]
