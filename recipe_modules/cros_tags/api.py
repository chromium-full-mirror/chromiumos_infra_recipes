# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
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
    tag_dict = {
        'parent_buildbucket_id': str(self.m.buildbucket.build.id),
        'snapshot': snapshot.id,
        'commit_position': str(snapshot.position),
        'hide-test-results-in-gerrit': 'true',
    }

    # TODO(b/186218358): Reevaluate if we need to create buildsets.
    if inherit_buildsets:
      tag_dict['buildset'] = [
          x.value
          for x in self.m.buildbucket.build.tags
          if x.key == 'buildset' and not x.value.startswith('commit/gitiles/')
      ]

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

  def get_values(self, key, tags=None, default=None):
    """Return a value from a list of tags.

    Since tags are able to have multiple values for the same key, the
    return value is always a list, even for a single item.

    Args:
      key (str): The key to lookup values for
      tags ([StringPair]): A list of tags in which to look up values.
        (defaults to tags for current build)
      default (str): A default value to return if no values found

    Returns:
      List of tag values, or [default] if none found.
    """
    tags = tags or self.m.buildbucket.build.tags

    results = []
    for tag in tags:
      if tag.key == key:
        results.append(tag.value)

    if not results and default is not None:
      return [default]
    return results

  def get_single_value(self, key, tags=None, default=None):
    """Return a single value from a list of tags.

    If the key has more than one value, only the first value will be returned.

    Args:
      key (str): The key to look up values for.
      tags ([StringPair]): A list of tags in which to look up values.
        (defaults to tags for current build)
      default (str): A default value to return if no values found.

    Returns:
      str|None, the first value found for the key among the tags.
    """
    tags = tags or self.m.buildbucket.build.tags
    for tag in tags:
      if tag.key == key:
        return tag.value
    return default

  def cq_cl_tag_value(self, cl_tag_key, tags):
    """Returns the value for the given cq_cl_tag, if it is found."""
    tag_prefix = cl_tag_key + ':'
    for t in tags:
      if t.key == 'cq_cl_tag' and t.value.startswith(tag_prefix):
        return t.value[len(tag_prefix):]
    return None

  @property
  def cq_equivalent_cl_group_key(self):
    """Return the cq_equivalent_cl_group_key, if any.

    Returns:
      (str) cq_equivalent_cl_group_key, or None
    """
    # If CQ is not active, then this tag should be ignored.
    if not self.m.cv.active:
      return None
    try:
      return self.m.cv.equivalent_cl_group_key
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
    if not self.m.cv.active:
      return None
    try:
      return self.m.cv.cl_group_key
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

  def add_tags_to_current_build(self, **tags):
    """Adds arbitrary tags during the runtime of a build.

    Args:
      **tags (dict): Dict mapping keys to values.  If the value is a list,
          multiple tags for the same key will be created.
    """
    self.m.buildbucket.add_tags_to_current_build(self.tags(**tags))
