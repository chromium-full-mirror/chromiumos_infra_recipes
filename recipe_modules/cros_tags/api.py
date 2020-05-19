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
    tags.append(
        self._key_value('parent_buildbucket_id',
                        str(self.m.buildbucket.build.id)))
    tags.append(self._key_value('snapshot', snapshot.id))
    tags.append(self._key_value('commit_position', str(snapshot.position)))
    group_key = self.cq_cl_group_key
    if group_key:
      tags.append(self._key_value('cq_cl_group_key', group_key))
    group_key = self.cq_equivalent_cl_group_key
    if group_key:
      tags.append(self._key_value('cq_equivalent_cl_group_key', group_key))
    return tags

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

  @property
  def cq_equivalent_cl_group_key(self):
    """Return the cq_equivalent_cl_group_key, if any.

    Returns:
      (str) cq_equivalent_cl_group_key, or None
    """
    # If CQ is not active, then this tag should be ignored.
    if self.m.cq.state == self.m.cq.INACTIVE:
      return None
    # TODO(crbug/1051623): once 2208069 is live, refactor this and add tests.
    try:
      # Fixed in crrev.com/c/2208069.
      return self.m.cq.equivalent_cl_group_key
    except ValueError:  # pragma: no cover
      # CQ (more likely, our tests) did not set a value.
      return None
    except AttributeError:
      # Crrev.com/c/2208069 has not landed yet.
      for t in self.m.buildbucket.build.tags:
        if t.key == 'cq_equivalent_cl_group_key':
          return t.value
    return None

  @property
  def cq_cl_group_key(self):
    """Return the cq_cl_group_key, if any.

    Returns:
      (str) cq_cl_group_key, or None
    """
    # If CQ is not active, then this tag should be ignored.
    if self.m.cq.state == self.m.cq.INACTIVE:
      return None
    try:
      # Fixed in crrev.com/c/2208069.
      return self.m.cq.cl_group_key
    except ValueError:
      # CQ (more likely, our tests) did not set a value.
      pass
    return None
