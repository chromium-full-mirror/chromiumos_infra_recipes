# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for managing CrOS code changes."""

from recipe_engine import recipe_api


class Change(object):
  """Change represents a single CrOS change (i.e. Gerrit patchset)."""

  INFO_ATTRS = ('project', 'branch', 'subject')

  def __init__(self, gerrit_change_info, patchset, host):
    """Initialize Change.

    Args:
      gerrit_change_info (dict): ChangeInfo as returned from Gerrit's API.
      patchset (int): Patchset of the change to use.
      host (str): Gerrit host where this Change was fetched from.
    """
    self.project = gerrit_change_info['project']
    self.branch = gerrit_change_info['branch']
    self.subject = gerrit_change_info['subject']
    self.number = int(gerrit_change_info['_number'])

    self.patchset = patchset
    self._host = host

  @property
  def url(self):
    """Returns a URL where this Change can be viewed."""
    return 'https://%s/%d' % (self._host, self.number)


class ChangesApi(recipe_api.RecipeApi):
  """A module for CrOS code change helpers."""

  def __init__(self, *args, **kwargs):
    """Initialize ChangeApi."""
    super(ChangesApi, self).__init__(*args, **kwargs)
    self._changes = None

  def _get_change(self, gerrit_change):
    """Fetch and return a single Change from Gerrit."""
    query_params = [('change', str(gerrit_change.change))]
    infos = self.m.gerrit.get_changes(gerrit_change.host,
                                      query_params=query_params,
                                      o_params=['ALL_REVISIONS'], limit=1)
    assert len(infos) == 1, 'expected 1 result, got %r' % infos
    return Change(infos[0], patchset=gerrit_change.patchset,
                  host=gerrit_change.host)

  def get_changes(self, cache=True):
    """Fetch and return Changes for this build.

    Args:
      cache (bool): If True, may return cached change information.
    """
    # TODO(lannm): See if we can batch these requests per-host.
    if not cache or self._changes is None:
      gerrit_changes = self.m.buildbucket.build.input.gerrit_changes
      self._changes = [self._get_change(x) for x in gerrit_changes]
    return self._changes
