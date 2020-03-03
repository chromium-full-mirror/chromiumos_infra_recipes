# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for generating tags."""

from recipe_engine import recipe_api

class CrosTagsApi(recipe_api.RecipeApi):
  """A module for generating tags."""

  def make_schedule_tags(self, snapshot):
    """Returns the tags typically added to scheduled child builders.

    Args:
      snapshot (GitilesCommit): snapshot the build was synced on

    Returns:
      list[{key, value}] to output as buildbucket tags
    """
    tags = []
    tags.append(self._key_value('parent_buildbucket_id',
                                str(self.m.buildbucket.build.id)))
    tags.append(self._key_value('snapshot', snapshot.id))
    return tags;

  def _key_value(self, key, value):
    return {
        'value': value,
        'key': key,
    }

  def has_entry(self, key, value, tags):
    """Returns whether tags contains a tag with key and value."""
    for t in tags:
      if (key, value) == (t.key, t.value):
        return True
    return False
