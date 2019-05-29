# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for managing Gerrit changes."""

import collections
import re

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from google.protobuf import json_format as jsonpb
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
    url = self._rev_info.get('fetch', {}).get('http', {}).get('url')
    if url is None:
      # No explicit fetch URL; build one ourselves.
      url = 'https://%s/%s' % (self.host, self.project)
    return url

  @property
  def git_fetch_ref(self):
    """Returns a ref where 'git fetch' can access this PatchSet."""
    ref = self._rev_info.get('fetch', {}).get('http', {}).get('ref')
    if ref is None:
      # No explicit fetch ref; use the RevisionInfo ref.
      ref = self._rev_info['ref']
    return ref

  @property
  def file_infos(self):
    """Returns a dict of {<path>: <FileInfo>}.

    Will return None if file info wasn't requested. See `include_files` on
    `gerrit.fetch_patch_sets`.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#file-info
    """
    return self._rev_info.get('files')


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

  def fetch_patch_sets(self, gerrit_changes, include_files=False,
                       test_output_data=None):
    """Fetch and return PatchSets from Gerrit.

    The step fails if any patch set is not found.

    Args:
      gerrit_changes (List[GerritChange]): Buildbucket GerritChanges to fetch.
      include_files (bool): If True, include information about changed files.
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

    request = {'changes': requests, 'include_files': include_files}
    results = self._gerrit_fetch_changes(request,
                                         test_output_data=test_output_data)

    # Validate all results present.
    patch_sets = []
    missing_responses = []
    for request, result in zip(requests, results['changes']):
      if result.get('revision_info') is None:
        missing_responses.append(request)
      else:
        patch_sets.append(PatchSet(result))

    if missing_responses:
      presentation = self.m.step.active_result.presentation
      presentation.status = self.m.step.FAILURE
      presentation.logs['missing gerrit patch set'] = [
          'no Gerrit patch set found for input %r' % r
          for r in missing_responses
      ]
      raise self.m.step.StepFailure('missing gerrit patch(es)')
    return patch_sets

  def parse_gerrit_change(self, gerrit_change_url):
    """Parse GerritChange proto from a gerrit change URL.

    This function expects the URL to be formatted as:

      https://<host>-review.googlesource.com/c/<project>/+/<change number>

    Args:
      gerrit_change_url (str): The change URL.

    Returns:
      GerritChange: The parsed proto.
    """
    assert gerrit_change_url, 'gerrit change URL must be nonempty'
    gerrit_change_url = gerrit_change_url.rstrip('/')

    # First check if this is a verbose Gerrit URL.
    match = re.match(
        r'(?:https://)?([^.]+)-review.googlesource.com/c/([^+]+)/\+/(\d+)(/\d+)?',
        gerrit_change_url)
    if match:
      host, project, change, patchset = match.groups()
      return GerritChange(
          host=host,
          project=project,
          change=int(change),
          patchset=int(patchset.lstrip('/')) if patchset else 0)

    # Otherwise, it's a dumb one.
    match = re.match(r'(?:https://)?([^.]+)-review.googlesource.com/(\d+)',
                     gerrit_change_url)
    assert match, 'malformed gerrit change URL: %s' % gerrit_change_url
    host, change = match.groups()
    return GerritChange(host=host, change=int(change))

  def changes_are_submittable(self, gerrit_changes, test_output_data=None):
    """Checks if the provided changes can be merged onto their Git branches.

    Args:
      gerrit_changes (list(common_pb2.GerritChange)): the changes to check

    Returns:
      bool: whether the changes are submittable
    """
    with self.m.step.nest('submittable changes check') as step:
      changes = []
      for gc in gerrit_changes:
        changes.append({
            'host': gc.host,
            'change_number': int(gc.change),
            'patch_set': int(gc.patchset),
        })
      req = {
        'gerrit_changes': changes,
        'temp_dir': self.m.path['cleanup'].join('submittable_check'),
      }
      if test_output_data is None:
        test_output_data = lambda: self.test_api.test_changes_are_submittable()
      result = self.m.support.call('git-test-submit', req,
                                   test_output_data=test_output_data)
      if result['errors']:
        step.presentation.step_text = 'Unable to cherry-pick changes'
        step.presentation.logs['cherry-pick-failures'] = result['errors']
        step.presentation.status = 'FAILURE'
        return False
      step.presentation.step_text = 'Confirmed changes can be cherry-picked'
      return True
