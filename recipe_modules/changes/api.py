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
    self._gerrit_change = gerrit_change_info
    self.host = host

    for commit_id, rev in gerrit_change_info['revisions'].items():
      if rev['_number'] == patchset:
        rev['_commit_id'] = commit_id
        self._gerrit_rev = rev
        break
    else:
      raise ValueError('gerrit_change_info has no patchset %d' % patchset)

  @property
  def project(self):
    """Returns the Change project."""
    return self._gerrit_change['project']

  @property
  def branch(self):
    """Returns the Change branch."""
    return self._gerrit_change['branch']

  @property
  def subject(self):
    """Returns the Change subject."""
    return self._gerrit_change['subject']

  @property
  def view_url(self):
    """Returns a URL where this Change can be viewed."""
    return 'https://%s/%d' % (self.host, self._gerrit_change['_number'])

  @property
  def git_fetch_url(self):
    """Returns a URL where 'git fetch' can access this Change."""
    return self._gerrit_rev['fetch']['http']['url']

  @property
  def git_fetch_ref(self):
    """Returns a ref where 'git fetch' can access this Change."""
    return self._gerrit_rev['fetch']['http']['ref']


class ChangesApi(recipe_api.RecipeApi):
  """A module for CrOS code change helpers."""

  def __init__(self, *args, **kwargs):
    """Initialize ChangeApi."""
    super(ChangesApi, self).__init__(*args, **kwargs)
    self._changes = None

  def _get_change(self, gerrit_change):
    """Fetch and return a single Change from Gerrit."""
    query_params = [('change', str(gerrit_change.change))]
    step_test_data = lambda: self.test_api.get_gerrit_change_data()
    infos = self.m.gerrit.get_changes(
        'https://%s' % gerrit_change.host, query_params=query_params,
        o_params=['ALL_REVISIONS'], limit=1, step_test_data=step_test_data)
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
