# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for generating tags."""

from recipe_engine import recipe_api

class CrosTagsApi(recipe_api.RecipeApi):
  """A module for generating tags."""

  def make_schedule_tags(self):
    """Returns the tags typically added to scheduled child builders.

    Returns:
      list[{key, value}] to output as buildbucket tags
    """
    return [{
        'key': 'parent_buildbucket_id',
        'value': str(self.m.buildbucket.build.id),
    }]
