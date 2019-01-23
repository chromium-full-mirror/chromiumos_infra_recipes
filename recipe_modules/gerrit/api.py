# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for managing Gerrit changes."""

import collections

from recipe_engine import recipe_api

# Strip these suffixes from hosts for "short" host display.
SHORT_HOST_SUFFIXES = ('-review.googlesource.com', '.googlesource.com')


class PatchSet(object):
  """PatchSet represents a single Gerrit patchset."""

  INFO_ATTRS = ('project', 'branch', 'subject')

  def __init__(self, change):
    """Initialize PatchSet.

    Args:
      change (dict): Change data as returned by gerrit-fetch-changes.
    """
    self.host = change['host']
    self._change_info = change['info']
    self._rev_info = change['revision_info']

  @property
  def short_host(self):
    """Returns the "short host" name for this PatchSet.

    This will be the full host name if it does not match a common host suffix.
    """
    host = self.host
    for suffix in SHORT_HOST_SUFFIXES:
      if host.endswith(suffix):
        host = host[:-len(suffix)]
        break
    return host

  @property
  def project(self):
    """Returns the PatchSet project."""
    return self._change_info['project']

  @property
  def branch(self):
    """Returns the PatchSet branch."""
    return self._change_info['branch']

  @property
  def subject(self):
    """Returns the PatchSet subject."""
    return self._change_info['subject']

  @property
  def display_id(self):
    """Returns a unique ID for this PatchSet for UI purposes."""
    return '%s:%d' % (self.short_host, self._change_info['_number'])

  @property
  def display_url(self):
    """Returns a URL where this PatchSet can be viewed."""
    return 'https://%s/%d' % (self.host, self._change_info['_number'])

  @property
  def git_fetch_url(self):
    """Returns a URL where 'git fetch' can access this PatchSet."""
    return self._rev_info['fetch']['http']['url']

  @property
  def git_fetch_ref(self):
    """Returns a ref where 'git fetch' can access this PatchSet."""
    return self._rev_info['fetch']['http']['ref']


class GerritApi(recipe_api.RecipeApi):
  """A module for Gerrit helpers."""

  def __init__(self, *args, **kwargs):
    """Initialize GerritApi."""
    super(GerritApi, self).__init__(*args, **kwargs)
    self._buildbucket_patch_sets = None

  def _gerrit_fetch_changes(self, input, test_output_data=None):
    """Call gerrit-fetch-changes support tool.

    Args:
      input (dict): Input data.
      test_output_data (dict): Test output for gerrit-fetch-changes.

    Returns:
      dict: Output data.
    """
    if test_output_data is None:
      test_output_data = lambda: self.test_api.test_gerrit_fetch_changes(input)
    return self.m.support.call('gerrit-fetch-changes', input,
                               test_output_data=test_output_data)

  def fetch_patch_sets(self, gerrit_changes, test_output_data=None):
    """Fetch and return PatchSets from Gerrit.

    The step fails if any patch set is not found.

    Args:
      gerrit_changes (List[GerritChange]): Buildbucket GerritChanges to fetch.
      test_output_data (dict): Test output for gerrit-fetch-changes.

    Returns:
      List[PatchSet]: List of PatchSets in requested order.
    """
    requests = []
    for gerrit_change in gerrit_changes:
      requests.append({
          'host': gerrit_change.host,
          'change_number': int(gerrit_change.change),
          'patch_set': int(gerrit_change.patchset),
      })

    request = {'changes': requests}
    results = self._gerrit_fetch_changes(request,
                                         test_output_data=test_output_data)

    # Validate all results present.
    call_presentation = self.m.step.active_result.presentation
    patch_sets = []
    for request, result in zip(requests, results['changes']):
      if result.get('revision_info') is None:
        call_presentation.status = self.m.step.FAILURE
        call_presentation.logs.setdefault(
            'missing gerrit patch set', []).append(
                'no Gerrit patch set found for input %r' % request)
        patch_sets.append(None)
      else:
        patch_sets.append(PatchSet(result))
    return patch_sets
