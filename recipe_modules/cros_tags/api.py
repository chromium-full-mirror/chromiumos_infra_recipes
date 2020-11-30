# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for generating tags."""

from recipe_engine import recipe_api


class CrosTagsApi(recipe_api.RecipeApi):
  """A module for generating tags."""

  def make_schedule_tags(self, snapshot, inherit_buildsets=True):
    """Returns the tags typically added to scheduled child builders.

    Args:
      snapshot (GitilesCommit): snapshot the build was synced on
      inherit_buildsets (bool): whether to include non-gitiles_commit buildsets.

    Returns:
      list[StringPair] to pass as buildbucket tags
    """
    # None of these tags is order specific.
    tag_dict = dict(
        parent_buildbucket_id=str(self.m.buildbucket.build.id),
        snapshot=snapshot.id,
        commit_position=str(snapshot.position),
    )

    if inherit_buildsets:
      buildsets = [
          x.value
          for x in self.m.buildbucket.build.tags
          if x.key == 'buildset' and not x.value.startswith('commit/gitiles/')
      ]
      if snapshot.host and snapshot.project and snapshot.id:
        buildsets.append('commit/gitiles/%s/%s/+/%s' %
                         (snapshot.host, snapshot.project, snapshot.id))
      tag_dict['buildset'] = buildsets

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

  def tags(self, **tags):
    """Helper for generating a list of StringPair messages.

    Args:
      tags (dict): Dict mapping keys to values.  If the value is a list,
          multiple tags for the same key will be created.

    Returns:
      (list[StringPair]) tags.
    """
    return self.m.buildbucket.tags(**tags)
