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
      list[StringPair] to pass as buildbucket tags
    """
    # None of these tags is order specific.
    tag_dict = dict(
        parent_buildbucket_id=str(self.m.buildbucket.build.id),
        snapshot=snapshot.id,
        commit_position=str(snapshot.position),
    )

    if self.cq_cl_group_key:
      tag_dict['cq_cl_group_key'] = self.cq_cl_group_key
    if self.cq_equivalent_cl_group_key:
      tag_dict['cq_equivalent_cl_group_key'] = self.cq_equivalent_cl_group_key
    return self.m.buildbucket.tags(**tag_dict)

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
    try:
      return self.m.cq.equivalent_cl_group_key
    except ValueError:
      # CQ (or more likely, our tests) did not set a value.
      pass
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
      return self.m.cq.cl_group_key
    except ValueError:
      # CQ (or more likely, our tests) did not set a value.
      pass
    return None
