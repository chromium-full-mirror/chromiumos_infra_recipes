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
from recipe_engine.recipe_api import RecipeApi, StepFailure

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
    # TODO(crbug/1146603): Consider changing to change['revision_info']['_number'].
    # change['patch_set'] appears to always be set to 0.
    self._patch_set = change['patch_set']

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
  def current_revision(self):
    """Returns the PatchSet current_revision."""
    return self._change_info['current_revision']

  @property
  def branch(self):
    """Returns the PatchSet branch."""
    return self._change_info['branch']

  @property
  def subject(self):
    """Returns the PatchSet subject."""
    return self._change_info['subject']

  @property
  def change_id(self):
    """Returns the int Change Number."""
    return self._change_info['_number']

  @property
  def display_id(self):
    """Returns a unique ID for this PatchSet for UI purposes."""
    return '%s:%d' % (self.short_host, self.change_id)

  @property
  def display_url(self):
    """Returns a URL where this PatchSet can be viewed."""
    return 'https://%s/c/%d' % (self.host, self.change_id)

  @property
  def created(self):
    """Returns the date string with when PatchSet was created."""
    return self._change_info['created']

  @property
  def updated(self):
    """Returns the date string with when PatchSet was last updated."""
    return self._change_info['updated']

  @property
  def patch_set(self):
    """Returns the int patch set number for this PatchSet."""
    return self._patch_set

  @property
  def submitted(self):
    """Returns the date string with when PatchSet was submitted (merged).

    Returns None if the PatchSet hasn't been merged.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
    """
    return self._change_info.get('submitted', None)

  @property
  def hashtags(self):
    """ Returns the hashtags associated with this PatchSet."""
    return self._change_info['hashtags']

  @property
  def messages(self):
    """Returns the messages associated with this PatchSet."""
    return self._change_info['messages']

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

  @property
  def commit_info(self):
    """Returns the CommitInfo for a patchet.

    Will return None if commit info wasn't requested. See `include_commit_info`
    on `gerrit.fetch_patch_sets`.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#commit-info
    """
    return self._rev_info.get('commit')

  def to_gerrit_change_proto(self):
    """Returns a GerritChange proto constructed from this patchset."""
    return GerritChange(host=self.host, change=self.change_id,
                        project=self.project, patchset=self.patch_set)


class Label(enum.Enum):
  """Describes some valid Gerrit labels. Not necessarily exhaustive."""

  # Whether or not the change can skip submit approvals.
  BOT_COMMIT = 1

  # Whether or not a change has been reviewed.
  CODE_REVIEW = 2

  # Describes how the change should be tested and/or whether it should
  # be submitted when finished.
  COMMIT_QUEUE = 3

  # Whether or not the CL has been manually tested.
  VERIFIED = 4

  @property
  def key(self):
    # FOO_BAR must be Foo-Bar when set via Gerrit.
    return '-'.join([
        word[0].upper() + word[1:].lower()
        for word in self.name.split('_')
        if word.strip()
    ])


class GerritApi(RecipeApi):
  """A module for Gerrit helpers."""

  PatchSet = PatchSet
  Label = Label

  def __init__(self, *args, **kwargs):
    """Initialize GerritApi."""
    super(GerritApi, self).__init__(*args, **kwargs)
    self._buildbucket_patch_sets = None

  def _gerrit_fetch_changes(self, input, gerrit_changes, test_output_data=None):
    """Call gerrit-fetch-changes support tool.

    Args:
      input (dict): Input data.
      test_output_data (dict): Test output for gerrit-fetch-changes.

    Returns:
      dict: Output data.
    """
    if test_output_data is None:
      test_output_data = lambda: self.test_api.test_gerrit_fetch_changes(
          input, gerrit_changes)
    return self.m.support.call('gerrit-fetch-changes', input,
                               test_output_data=test_output_data,
                               timeout=10 * 60)

  def fetch_patch_sets(self, gerrit_changes, include_files=False,
                       include_commit_info=False, include_messages=False,
                       test_output_data=None):
    """Fetch and return PatchSets from Gerrit.

    The step fails if any patch set is not found.

    Args:
      gerrit_changes (List[GerritChange]): Buildbucket GerritChanges to fetch.
      include_files (bool): If True, include information about changed files.
      include_commit_info (bool): If True, include information about the commit.
      include_messages (bool): If True, include messages attached to the commit.
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

    request = {
        'changes': requests,
        'include_files': include_files,
        'include_commit_info': include_commit_info,
        'include_messages': include_messages,
    }
    results = self._gerrit_fetch_changes(request, gerrit_changes,
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
      raise StepFailure('missing gerrit patch(es)')
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
      return GerritChange(host=host, project=project, change=int(change),
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

  def assert_changes_submittable(self, gerrit_changes, test_output_data=None):
    """Checks if the provided changes can be merged onto their Git branches.

    Args:
      gerrit_changes (list(common_pb2.GerritChange)): the changes to check

    Raises:
      StepFailure if the changes cannot be merged.
    """
    with self.m.step.nest('check for merge conflicts') as presentation:
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
        presentation.step_text = 'unable to cherry-pick changes'
        presentation.logs['cherry-pick-failures'] = result['errors']
        presentation.status = 'FAILURE'
        presentation.properties['merge_conflict'] = True
        # Write an error into the failure so that it's surfaced to the user.
        # Currently the program only returns one error, so just use the first.
        error_markdown_lines = [
            '    {}'.format(s) for s in result['errors'][0].splitlines()
        ]
        error_msg = '\n'.join(error_markdown_lines)
        raise StepFailure(
            'Merge conflict detected! Please rebase and retry.\n\n{}'.format(
                error_msg))
      presentation.step_text = 'confirmed no merge conflicts'
      return

  def create_change(self, project, reviewers=None, ccs=None, topic=None,
                    hashtags=None):
    """Create a Gerrit change for the most recent commits in the given project.

    Assumes one or more local commits exists in the project. The commit message
    is always used as the CL description.

    Args:
      project (str|Path): Any path within the project of interest.
      reviewers (list[str]): List of reviewer emails. If specified, gerrit will
          email the reviewers.
      ccs (list[str]): List of cc emails. If specified, gerrit will cc the
          individuals.
      topic (str): Topic to set for the CL.
      hashtags (list[str]): List of hashtags to set for the CL.

    Returns:
      GerritChange: The newly created change.
    """
    with self.m.step.nest('create gerrit change for %s' % project) as pres:
      with self.m.context(cwd=self.m.src_state.workspace_path):
        project_info = self.m.repo.project_info(project)

      with self.m.context(
          cwd=self.m.src_state.workspace_path.join(project_info.path)):
        self.m.git_cl.upload(reviewers=reviewers, ccs=ccs, topic=topic,
                             hashtags=hashtags, send_mail=True)
        gerrit_change_url = self.m.git_cl.status(
            field='url', fast=True, step_test_data=functools.partial(
                self.m.raw_io.test_api.stream_output,
                self.test_api.test_gerrit_change_url()))
        pres.links['link to change'] = gerrit_change_url

        # The URL does not always include the project name, so always set it.
        change = self.parse_gerrit_change(gerrit_change_url)
        change.project = project_info.name
        return change

  def set_change_labels_remote(self, gerrit_change, fetch_ref, labels):
    """Set the given labels for the given Gerrit change.
      set_change_labels only works when the change exists in the local checkout.
      This function should be used in other cases.

    Args:
      gerrit_change (GerritChange): The change of interest.
      fetch_ref (str): The ref at which the change can be fetched.
      labels (dict): Mapping from label (Label) to value (int).

    Returns:
      str: The new label ref (primarily for testing).
    """
    with self.m.context(cwd=self.m.src_state.workspace_path):
      project_info = self.m.repo.project_info(gerrit_change.project)

    with self.m.git.head_context():
      # Fetch the the given Gerrit change.
      self.m.git.fetch(project_info.remote, [fetch_ref], timeout_sec=60)
      # Temporarily checkout the fetched ref.
      self.m.git.checkout("FETCH_HEAD")

      ref = self._set_change_labels(gerrit_change, labels,
                                    rebase_from_remote=True)

      return ref

  def set_change_labels(self, gerrit_change, labels):
    """Set the given labels for the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      labels (dict): Mapping from label (Label) to value (int).

    Returns:
      str: The new label ref (primarily for testing).
    """
    return self._set_change_labels(gerrit_change, labels)

  def _set_change_labels(self, gerrit_change, labels, rebase_from_remote=False):
    """Set the given labels for the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      labels (dict): Mapping from label (Label) to value (int).
      rebase_from_remote (bool): If true, sets the rebase branch to the equiv.
        of origin/master (usually cros/master).

    Returns:
      str: The new label ref (primarily for testing).
    """
    with self.m.step.nest('set labels on CL %d' % gerrit_change.change) as pres:
      full_labels = sorted(
          ['%s+%d' % (label.key, value) for label, value in labels.iteritems()])
      pres.step_text = ','.join(full_labels)
      pres.links['link to change'] = self.parse_gerrit_change_url(gerrit_change)

      with self.m.context(cwd=self.m.src_state.workspace_path):
        project_info = self.m.repo.project_info(gerrit_change.project)

      branch = project_info.branch.split('/')[-1]
      ref = 'refs/for/%s%%%s' % (branch, ','.join(
          ['l=%s' % label for label in full_labels]))
      refspec = 'HEAD:%s' % ref
      with self.m.context(
          cwd=self.m.src_state.workspace_path.join(project_info.path)):
        # Rebase before pushing so Gerrit does not complain there was no change.
        rebase_branch = branch = "%s/%s" % (
            project_info.remote, branch) if rebase_from_remote else None
        self.m.git.rebase(force=True, branch=rebase_branch)
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
    with self.m.step.nest('comment on CL %d' % gerrit_change.change) as pres:
      pres.logs['comment text'] = [comment]
      pres.links['link to change'] = self.parse_gerrit_change_url(gerrit_change)

      with self.m.context(cwd=self.m.src_state.workspace_path):
        project_info = self.m.repo.project_info(gerrit_change.project)

      with self.m.context(
          cwd=self.m.src_state.workspace_path.join(project_info.path)):
        self.m.git_cl('comment', ['-i', gerrit_change.change, '-a', comment])

  def get_change_description(self, gerrit_change):
    """Get the description of the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.

    Returns:
      str: The change description.
    """
    with self.m.step.nest('get CL %d description' %
                          gerrit_change.change) as pres:
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      pres.links['link to change'] = gerrit_change_url
      patch_set = self.fetch_patch_sets([gerrit_change],
                                        include_commit_info=True)[0]
      description = patch_set.commit_info.get('message')
      # Make sure that there is a trailing newline.
      description = (
          description if description.endswith('\n') else description + '\n')
      pres.logs['description text'] = [description]
      return description

  def set_change_description(self, gerrit_change, description):
    """Set the description of the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      description (str): The new description, in full. Be sure this still
          includes the Change-Id and other essential metadata.
    """
    with self.m.step.nest('set CL %d description' %
                          gerrit_change.change) as pres:
      # Make sure that there is a trailing newline.
      description = (
          description if description.endswith('\n') else description + '\n')
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      pres.links['link to change'] = gerrit_change_url
      pres.logs['description text'] = [description]

      with self.m.context(cwd=self.m.src_state.workspace_path):
        project_info = self.m.repo.project_info(gerrit_change.project)

      with self.m.context(
          cwd=self.m.src_state.workspace_path.join(project_info.path)):
        self.m.git_cl.set_description(description, patch_url=gerrit_change_url)

  def abandon_change(self, gerrit_change, message=None):
    """Abandon the given change.

    Args:
      gerrit_change (GerritChange): The change to abandon.
      message (str): Optional message to post to change.
    """
    with self.m.step.nest('abandon CL %d' % gerrit_change.change) as pres:
      pres.links['link to change'] = self.parse_gerrit_change_url(gerrit_change)

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
    with self.m.step.nest('query %s' % host) as presentation:
      results = self.m.depot_tools_gerrit.get_changes(host, query_params)
      prefix = 'https://'
      changes = [
          GerritChange(
              host=host[len(prefix):] if host.startswith(prefix) else host,
              project=result['project'],
              change=int(result['_number']),
          ) for result in results
      ]

      presentation.step_text = 'found %d matching CLs' % len(changes)
      for change in changes:
        change_url = self.parse_gerrit_change_url(change)
        presentation.links['found CL %d' % change.change] = change_url

      return changes
