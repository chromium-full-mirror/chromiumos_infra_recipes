# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for managing Gerrit changes."""

import collections
import enum
import functools
import re
import urllib

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


class Label(enum.Enum):
  """Describes some valid Gerrit labels. Not necessarily exhaustive."""

  # Whether or not the change can skip submit approvals.
  BOT_COMMIT = 1;

  # Whether or not a change has been reviewed.
  CODE_REVIEW = 2;

  # Describes how the change should be tested and/or whether it should
  # be submitted when finished.
  COMMIT_QUEUE = 3;

  # Whether or not the CL has been manually tested.
  VERIFIED = 4;

  @property
  def key(self):
    # FOO_BAR must be Foo-Bar when set via Gerrit.
    return '-'.join([
        word[0].upper() + word[1:].lower()
        for word in self.name.split('_') if word.strip()
    ])


class GerritApi(recipe_api.RecipeApi):
  """A module for Gerrit helpers."""

  PatchSet = PatchSet
  Label = Label

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
    match = re.match(r'(?:https://)?([^/]+)/c/(?:([^+]+)/\+/)?(\d+)(/\d+)?',
                     gerrit_change_url)
    if match:
      host, project, change, patchset = match.groups()
      return GerritChange(
          host=host,
          project=project,
          change=int(change),
          patchset=int(patchset.lstrip('/')) if patchset else 0)

    # Otherwise, it's a dumb one.
    match = re.match(r'(?:https://)?([^/]+)/(\d+)', gerrit_change_url)
    assert match, 'malformed gerrit change URL: %s' % gerrit_change_url
    host, change = match.groups()
    return GerritChange(host=host, change=int(change))

  def parse_gerrit_change_url(self, gerrit_change):
    """Transform a GerritChange proto into a Gerrit change URL.

    Args:
      gerrit_change (GerritChange): The change in question.

    Returns:
      str: The Gerrit URL.
    """
    assert gerrit_change.host, 'found GerritChange with no host'
    assert gerrit_change.change, 'found GerritChange with no change number'

    qualified_host = self.parse_qualified_gerrit_host(gerrit_change)
    if gerrit_change.project:
      url = '%s/c/%s/+/%d' % (qualified_host, gerrit_change.project.strip('/'),
                              gerrit_change.change)
      if gerrit_change.patchset:
        url = '%s/%d' % (url, gerrit_change.patchset)
      return url
    else:
      return '%s/%d' % (qualified_host, gerrit_change.change)

  def parse_qualified_gerrit_host(self, gerrit_change):
    """Transform a GerritChange proto into a fully qualified host.

    Args:
      gerrit_change (GerritChange): The change in question.

    Returns:
      str: The fully qualified Gerrit host.
    """
    host = gerrit_change.host
    for prefix in ('http://', 'https://'):
      if host.startswith(prefix):
        host = host[len(prefix):]
    return 'https://' + host

  def changes_are_submittable(self, gerrit_changes, test_output_data=None):
    """Checks if the provided changes can be merged onto their Git branches.

    Args:
      gerrit_changes (list(common_pb2.GerritChange)): the changes to check

    Returns:
      bool: whether the changes are submittable
    """
    with self.m.step.nest('check for merge conflicts') as step:
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
        step.presentation.step_text = 'unable to cherry-pick changes'
        step.presentation.logs['cherry-pick-failures'] = result['errors']
        step.presentation.status = 'FAILURE'
        return False
      step.presentation.step_text = 'confirmed no merge conflicts'
      return True

  def create_change(self, project, reviewers=None, topic=None):
    """Create a Gerrit change for the most recent commits in the given project.

    Assumes one or more local commits exists in the project. The commit message
    is always used as the CL description.

    Args:
      project (str|Path): Any path within the project of interest.
      reviewers (list[str]): List of reviewer emails. If specified, gerrit will
          email the reviewers.
      topic (str): Topic to set for the CL.

    Returns:
      GerritChange: The newly created change.
    """
    with self.m.step.nest('create gerrit change for %s' % project) as step:
      with self.m.context(cwd=self.m.cros_source.workspace_path):
        project_info = self.m.repo.project_info([project])

      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project_info.path)):
        self.m.git_cl.upload(reviewers=reviewers, topic=topic, send_mail=True)
        gerrit_change_url = self.m.git_cl.status(
            field='url', fast=True,
            step_test_data=functools.partial(
                self.m.raw_io.test_api.stream_output,
                self.test_api.test_gerrit_change_url()))
        step.presentation.links['link to change'] = gerrit_change_url

        # The URL does not always include the project name, so always set it.
        change = self.parse_gerrit_change(gerrit_change_url)
        change.project = project_info.name
        return change

  def set_change_labels(self, gerrit_change, labels):
    """Set the given labels for the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      labels (dict): Mapping from label (Label) to value (int).

    Returns:
      str: The new label ref (primarily for testing).
    """
    with self.m.step.nest('set labels on CL %d' % gerrit_change.change) as step:
      full_labels = sorted([
          '%s+%d' % (label.key, value) for label, value in labels.iteritems()])
      step.presentation.step_text = ','.join(full_labels)
      step.presentation.links['link to change'] = self.parse_gerrit_change_url(
          gerrit_change)

      with self.m.context(cwd=self.m.cros_source.workspace_path):
        project_info = self.m.repo.project_info([gerrit_change.project])

      branch = project_info.branch.split('/')[-1]
      ref = 'refs/for/%s%%%s' % (
          branch, ','.join(['l=%s' % label for label in full_labels]))
      refspec = 'HEAD:%s' % ref
      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project_info.path)):
        # Rebase before pushing so Gerrit does not complain there was no change.
        self.m.git.rebase(force=True)
        self.m.git.push(project_info.remote, refspec)

      return ref

  def add_change_comment(self, gerrit_change, comment):
    """Add a comment to the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change to post to.
      comment (str): The comment to post.

    Returns:
      str: The new message ref (primarily for testing).
    """
    with self.m.step.nest('comment on CL %d' % gerrit_change.change) as step:
      step.presentation.logs['comment text'] = [comment]
      step.presentation.links['link to change'] = self.parse_gerrit_change_url(
          gerrit_change)

      with self.m.context(cwd=self.m.cros_source.workspace_path):
        project_info = self.m.repo.project_info([gerrit_change.project])

      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project_info.path)):
        self.m.git_cl('comment', ['-a', comment])

  def get_change_description(self, gerrit_change):
    """Get the description of the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.

    Returns:
      str: The change description.
    """
    with self.m.step.nest(
        'get CL %d description' % gerrit_change.change) as step:
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      step.presentation.links['link to change'] = gerrit_change_url

      with self.m.context(cwd=self.m.cros_source.workspace_path):
        project_info = self.m.repo.project_info([gerrit_change.project])

      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project_info.path)):
        # Use `git cl` because depot_tools/gerrit does not support
        # getting description for the latest patch. That is, you must
        # always supply the patch number, and many of our applications
        # do not know it.
        description = self.m.git_cl.get_description(
            patch_url=gerrit_change_url, codereview='gerrit',
            step_test_data=functools.partial(
                self.m.raw_io.test_api.stream_output,
                self.test_api.test_gerrit_change_description()))

      step.presentation.logs['description text'] = [description.stdout]
      return description

  def set_change_description(self, gerrit_change, description):
    """Set the description of the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      description (str): The new description, in full. Be sure this still
          includes the Change-Id and other essential metadata.
    """
    with self.m.step.nest(
        'set CL %d description' % gerrit_change.change) as step:
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      step.presentation.links['link to change'] = gerrit_change_url
      step.presentation.logs['description text'] = [description]

      with self.m.context(cwd=self.m.cros_source.workspace_path):
        project_info = self.m.repo.project_info([gerrit_change.project])

      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project_info.path)):
        self.m.git_cl.set_description(description, patch_url=gerrit_change_url,
                                      codereview='gerrit')

  def abandon_change(self, gerrit_change, message=None):
    """Abandon the given change.

    Args:
      gerrit_change (GerritChange): The change to abandon.
      message (str): Optional message to post to change.
    """
    with self.m.step.nest('abandon CL %d' % gerrit_change.change) as step:
      step.presentation.links['link to change'] = self.parse_gerrit_change_url(
          gerrit_change)

      self.m.depot_tools_gerrit.abandon_change(
          self.parse_qualified_gerrit_host(gerrit_change), gerrit_change.change,
          message=message)

  def query_changes(self, host, query_params):
    """Query gerrit for the given changes.

    Args:
      host (str): The Gerrit host to query.
      query_params (list[(str, str)]): Query parameters as list of (key, value) tuples
          to form a query as documented here:
          https://gerrit-review.googlesource.com/Documentation/user-search.html#search-operators

    Returns:
      list[GerritChange]: Changes that match the query.
    """
    with self.m.step.nest('query %s' % host) as step:
      results = self.m.depot_tools_gerrit.get_changes(host, query_params)
      prefix = 'https://'
      changes = [
          GerritChange(
              host=host[len(prefix):] if host.startswith(prefix) else host,
              project=result['project'],
              change=int(result['_number']),
          )
          for result in results
      ]

      step.presentation.step_text = 'found %d matching CLs' % len(changes)
      for change in changes:
        change_url = self.parse_gerrit_change_url(change)
        step.presentation.links['found CL %d' % change.change] = change_url

      return changes
