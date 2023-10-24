# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for managing Gerrit changes."""

from datetime import timedelta
import enum
import json
import functools
import re
import typing
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Union

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.gerrit import GerritProperties

from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.config_types import Path
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

# Commonly used Gerrit hosts.
EXTERNAL_HOST = 'https://chromium-review.googlesource.com'
INTERNAL_HOST = 'https://chrome-internal-review.googlesource.com'

# Strip these suffixes from hosts for "short" host display.
SHORT_HOST_SUFFIXES = ('-review.googlesource.com', '.googlesource.com')

# JSONObject is a JSON object: a dict where all keys are strings, and the types
# of the values vary (and can themselves be JSONObject).
# The Gerrit API uses lots of these: for example, FileInfo and ChangeInfo at:
# https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html
JSONObject = Dict[str, Any]

# ChangeInfo is a JSON representation of a single Gerrit change, as returned by
# the Gerrit API. It is documented at:
# https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
ChangeInfo = JSONObject


def strip_xssi_prefix(json_string: str):
  # Remove the magic prefix against XSSI attack in the response.
  # See https://gerrit-review.googlesource.com/Documentation/rest-api.html#output
  # TODO(b:264623293): replace this with removeprefix() when we're on Python 3.9.
  return json_string[4:] if json_string.startswith(")]}'") else json_string


class PatchSet:
  """PatchSet represents a single Gerrit patchset.

  For details on the various fields, see Gerrit's ChangeInfo entity:
  https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
  """

  INFO_ATTRS = ('project', 'branch', 'subject')

  def __init__(self, change: JSONObject):
    """Initialize PatchSet.

    Args:
      change: Change data as returned by gerrit-fetch-changes.
    """
    self.host = change['host']
    self._change_info = change['info']
    self._rev_info = change['revision_info']
    self._patch_set = self._rev_info.get('_number', 0)
    self._patch_set_revision = change['patch_set_revision']

  @property
  def short_host(self) -> str:
    """Return the "short host" name for this PatchSet.

    This will be the full host name if it does not match a common host suffix.
    """
    host = self.host
    for suffix in SHORT_HOST_SUFFIXES:
      if host.endswith(suffix):
        host = host[:-len(suffix)]
        break
    return host

  @property
  def project(self) -> str:
    """Return the PatchSet's project."""
    return self._change_info['project']

  @property
  def current_revision(self) -> str:
    """Return the PatchSet's current_revision."""
    return self._change_info['current_revision']

  @property
  def branch(self) -> str:
    """Return the PatchSet's branch.

    The refs/head/ prefix is always omitted.
    """
    return self._change_info['branch']

  @property
  def subject(self) -> str:
    """Return the PatchSet's subject."""
    return self._change_info['subject']

  @property
  def change_id(self) -> int:
    """Return the Patch Set's change number."""
    return self._change_info['_number']

  @property
  def display_id(self) -> str:
    """Return a unique ID for this PatchSet for UI purposes."""
    return f'{self.short_host}:{self.change_id}'

  @property
  def display_url(self) -> str:
    """Return a URL where this PatchSet can be viewed."""
    return f'https://{self.host}/c/{self.change_id}'

  @property
  def created(self) -> str:
    """Return the date string with when PatchSet was created."""
    return self._change_info['created']

  @property
  def updated(self) -> str:
    """Return the date string with when PatchSet was last updated."""
    return self._change_info['updated']

  @property
  def patch_set(self) -> int:
    """Return the patch set number for this PatchSet."""
    return self._patch_set

  @property
  def patch_set_revision(self) -> str:
    """Return the patch set revision for this PatchSet."""
    return self._patch_set_revision

  @property
  def status(self) -> str:
    """Return the PatchSet status string."""
    return self._change_info['status']

  @property
  def submitted(self) -> Optional[str]:
    """Return the date string with when this PatchSet was submitted (merged).

    Returns None if the PatchSet hasn't been merged.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
    """
    return self._change_info.get('submitted', None)

  @property
  def submittable(self) -> bool:
    """Return the bool if PatchSet has been approved by the project submit rules.

    Returns False if the PatchSet don't have submittable field set.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
    """
    return self._change_info.get('submittable', False)

  @property
  def topic(self) -> str:
    """Return the topic associated with this PatchSet."""
    return self._change_info['topic']

  @property
  def hashtags(self) -> List[str]:
    """Return the hashtags associated with this PatchSet."""
    return self._change_info['hashtags']

  @property
  def labels(self) -> Optional[JSONObject]:
    """Return the labels applied to this PatchSet.

    Will return None if detailed labels weren't requested. See
    `include_detailed_labels` on `gerrit.fetch_patch_sets`.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#label-info
    """
    return self._change_info.get('labels')

  @property
  def messages(self) -> Optional[List[JSONObject]]:
    """Return the messages associated with this PatchSet."""
    return self._change_info['messages']

  @property
  def git_fetch_url(self) -> str:
    """Return a URL where `git fetch` can access this PatchSet."""
    url = self._rev_info.get('fetch', {}).get('http', {}).get('url')
    if url is None:
      # No explicit fetch URL; build one ourselves.
      url = 'https://%s/%s' % (self.host, self.project)
    return url

  @property
  def git_fetch_ref(self) -> str:
    """Return a ref where `git fetch` can access this PatchSet."""
    ref = self._rev_info.get('fetch', {}).get('http', {}).get('ref')
    if ref is None:
      # No explicit fetch ref; use the RevisionInfo ref.
      ref = self._rev_info['ref']
    return ref

  @property
  def file_infos(self) -> Optional[Dict[str, JSONObject]]:
    """Return a dict of {<path>: <FileInfo>} for all files modified by this PS.

    Will return None if file info wasn't requested. See `include_files` on
    `gerrit.fetch_patch_sets`.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#file-info
    """
    return self._rev_info.get('files')

  @property
  def work_in_progress(self) -> bool:
    """Return the work_in_progress status for PatchSet.

    Returns False if the PatchSet don't have work_in_progress field set.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
    """
    return self._change_info.get('work_in_progress', False)

  @property
  def commit_info(self) -> JSONObject:
    """Return the CommitInfo for this PatchSet.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#commit-info

    Raises:
      InfraFailure: If commit info wasn't requested when the patch set was
      fetched. See `include_commit_info` on `gerrit.fetch_patch_sets`.
    """
    if 'commit' not in self._rev_info:
      raise InfraFailure(
          f'No commit info for PatchSet {self.display_id}. '
          'Try adding include_commit_info=True into gerrit.fetch_patch_sets().')
    return self._rev_info['commit']

  def is_latest_patch_set(self) -> Optional[bool]:
    """Return whether the PatchSet is the latest.

    Sometime patch_set_revision is empty, then return False.
    """
    return self.current_revision == self.patch_set_revision if self.patch_set_revision else False

  @property
  def unresolved_comment_count(self) -> int:
    """Return the number of unresolved comments on the PatchSet.

    This is an optional field on ChangeInfo, returns 0 if it is not set.

    See: https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
    """
    return self._change_info.get('unresolved_comment_count', 0)

  def has_label_vote(self, label_name: str, value: int) -> bool:
    """Return whether the PatchSet includes given value for the given label.

    Args:
      label_name: The label name for which function checks if it has given value.
      value: The given vote that we looking for.
    Raises:
      InfraFailure: If detailed labels wasn't requested when the patch set was
      fetched. See `include_detailed_labels` on `gerrit.fetch_patch_sets`.
    """
    if self.labels is None:
      raise InfraFailure(
          f'No detailed labels for PatchSet {self.display_id}. '
          'Try adding include_detailed_labels=True into gerrit.fetch_patch_sets().'
      )
    return any(
        x.get('value') == value
        for x in self.labels.get(label_name, {}).get('all', []))

  def to_gerrit_change_proto(self) -> GerritChange:
    """Return a GerritChange proto constructed from this patchset."""
    return GerritChange(host=self.host, change=self.change_id,
                        project=self.project, patchset=self.patch_set)


class Label(enum.Enum):
  """Describe some valid Gerrit labels. Not necessarily exhaustive."""

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
  def key(self) -> str:
    """Return the label in a format readable by the Gerrit API.

    Gerrit expects labels to be in hyphenated camel case: Foo-Bar, Bot-Commit.
    """
    return '-'.join(
        [word.title() for word in self.name.split('_') if word.strip()])


class LabelConstraintKind(enum.Enum):
  """When querying changes, kinds of constraint one can apply to a label."""
  # APPROVED and UNAPPROVED refer whether to the change label JSON has been
  # "approved". The exact meaning of this varies by the label, but it is always
  # represented by the label's "approved" attribute.
  APPROVED = 1
  UNAPPROVED = 2

  # ANY_NONZERO_VOTE refers to any change for which any user has applied a
  # nonzero vote.
  # Votes are represented by the label's "all" attribute.
  ANY_NONZERO_VOTE = 3


class LabelConstraint(NamedTuple):
  """Constraint for Gerrit query results by label status, like (un)approved."""
  label: Label
  kind: LabelConstraintKind


def _does_change_label_satisfy_constraint(change_info: ChangeInfo,
                                          constraint: LabelConstraint) -> bool:
  """Return whether or not the Gerrit change JSON meets the label constraint.

  Args:
    change_info: JSON-like dict representing a single Gerrit change, as returned
      by api.depot_tools_gerrit.get_changes(o_params=['LABELS']).
    constraint: The constraint to compare against the change.

  Raises:
    KeyError: If change_info does not contain the 'labels' key.
    KeyError: If change_info['labels'] does not contain the label being checked.
  """
  try:
    change_labels_json = change_info['labels']
  except KeyError as e:
    raise StepFailure(
        'Gerrit change JSON does not contain key `labels`. Maybe '
        'get_changes() was called without o_params=["LABELS"]?\n\n%s' %
        change_info) from e
  try:
    label_json = change_labels_json[constraint.label.key]
  except KeyError as e:
    raise StepFailure('Gerrit change labels do not contain key %s: %s' %
                      (constraint.label.key, change_labels_json)) from e
  if constraint.kind == LabelConstraintKind.APPROVED:
    return 'approved' in label_json
  if constraint.kind == LabelConstraintKind.UNAPPROVED:
    return 'approved' not in label_json
  if constraint.kind == LabelConstraintKind.ANY_NONZERO_VOTE:
    return any(
        vote_json.get('value', 0) != 0
        for vote_json in label_json.get('all', []))
  raise StepFailure(f'Unexpected LabelConstraintKind: {constraint.kind}')


def _do_change_labels_satisfy_constraints(
    change_info: ChangeInfo, constraints: List[LabelConstraint]) -> bool:
  """Return whether or not the Gerrit change JSON meet the label constraints.

  Args:
    change_info: JSON-like dict representing a single Gerrit change, as returned
      by api.depot_tools_gerrit.get_changes(o_params=['LABELS']).
    constraints: The constraints to compare against the change.
  """
  return all(
      _does_change_label_satisfy_constraint(change_info, constraint)
      for constraint in constraints)


class GerritApi(RecipeApi):
  """A module for Gerrit helpers."""

  def __init__(self, properties: GerritProperties, *args, **kwargs):
    """Initialize GerritApi."""
    super().__init__(*args, **kwargs)
    self._buildbucket_patch_sets = None
    self._GET_CHANGE_DESCRIPTION_CACHE = {}
    self._properties = properties
    # Support for gerrit_related_changes gobin.
    self._related_changes_path = None

  def _gerrit_fetch_changes(
      self, request: JSONObject, test_gerrit_changes: List[GerritChange],
      step_name: Optional[str] = None,
      test_output_data: Optional[Callable] = None) -> JSONObject:
    """Call the gerrit-fetch-changes support tool directly.

    This tool is located at infra/recipes/support/gerrit-fetch-changes/.

    Returns:
      The JSON dict outputted by gerrit-fetch-changes.
    """
    if test_output_data is None:
      test_output_data = lambda: self.test_api.test_gerrit_fetch_changes(
          request, test_gerrit_changes)
    return self.m.support.call('gerrit-fetch-changes', request,
                               test_output_data=test_output_data,
                               timeout=36 * 60, name=step_name)

  def fetch_patch_sets(
      self, gerrit_changes: List[GerritChange], include_files: bool = False,
      include_commit_info: bool = False, include_messages: bool = False,
      include_submittable: bool = False, include_detailed_labels: bool = False,
      step_name: Optional[str] = None,
      test_output_data: Optional[Callable] = None) -> List[PatchSet]:
    """Fetch and return PatchSets from Gerrit.

    Args:
      gerrit_changes: Buildbucket GerritChanges to fetch.
      include_files: If True, include information about changed files.
      include_commit_info: If True, include information about the commit.
      include_messages: If True, include messages attached to the commit.
      include_submittable: If True, include information about possible
        submission.
      include_detailed_labels: If True, include information about the labels
        applied to the change.
      step_name: The name of the step.
      test_output_data: Test output for gerrit-fetch-changes.

    Returns:
      List of PatchSets in requested order.

    Raises:
      StepFailure: If any of the requested patch sets is not found.
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
        'include_submittable': include_submittable,
        'include_detailed_labels': include_detailed_labels,
    }

    try:
      results = self._gerrit_fetch_changes(request, gerrit_changes, step_name,
                                           test_output_data=test_output_data)
    finally:
      # Always log the request for debugging purposes.
      presentation = self.m.step.active_result.presentation
      presentation.logs['request'] = json.dumps(request)

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
          'no Gerrit patch set found for input {}'.format(
              json.dumps(r, sort_keys=True)) for r in missing_responses
      ]
      raise StepFailure('missing gerrit patch(es)')
    return patch_sets

  def fetch_patch_set_from_change(self, change: GerritChange,
                                  include_files: bool = False,
                                  include_commit_info: bool = False,
                                  test_output_data: Optional[Callable] = None
                                 ) -> PatchSet:
    """Fetch and return PatchSet associated with the given GerritChange.

    Assumes that change.patchset is set (which is not always the case).

    Args:
      gerrit_changes: Buildbucket GerritChange to fetch.
      include_files: If True, include information about changed files.
      test_output_data: Test output for gerrit-fetch-changes.
      include_commit_info: If True, include information about the commit.

    Raises:
      StepFailure: If the requested patch set is not found.
    """
    patch_sets = self.fetch_patch_sets([change], include_files=include_files,
                                       test_output_data=test_output_data,
                                       include_commit_info=include_commit_info)
    patch_sets = [x for x in patch_sets if x.patch_set == change.patchset]
    if not patch_sets:
      raise StepFailure('missing gerrit patch')
    return patch_sets[0]

  def parse_gerrit_change(self, gerrit_change_url: str) -> GerritChange:
    """Return a GerritChange proto, parsed from the gerrit change URL.

    This function expects the URL to be in one of these formats:

      https://<host>/c/<project>/+/<change-number>
      https://<host>/<change-number>

    ...where <host> is something like 'chromium-review.googlesource.com',
    <project> is something like 'chromiumos/chromite',
    and <change-number> is something like 12345.
    The https:// is optional.
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

    # Otherwise, it's a short one.
    match = re.match(r'(?:https://)?([^/]+)/(\d+)', gerrit_change_url)
    assert match, 'malformed gerrit change URL: %s' % gerrit_change_url
    host, change = match.groups()
    return GerritChange(host=host, change=int(change))

  def parse_gerrit_change_url(self, gerrit_change: GerritChange) -> str:
    """Return a Gerrit change URL, parsed from a GerritChange proto."""
    assert gerrit_change.host, 'found GerritChange with no host'
    assert gerrit_change.change, 'found GerritChange with no change number'

    qualified_host = self.parse_qualified_gerrit_host(gerrit_change)
    if not gerrit_change.project:
      return f'{qualified_host}/{gerrit_change.change}'
    project = gerrit_change.project.strip('/')
    url = f'{qualified_host}/c/{project}/+/{gerrit_change.change}'
    if gerrit_change.patchset:
      url = f'{url}/{gerrit_change.patchset}'
    return url

  def parse_qualified_gerrit_host(self, gerrit_change: GerritChange) -> str:
    """Return a fully qualified host parsed from a GerritChange proto."""
    host = gerrit_change.host
    for prefix in ('http://', 'https://'):
      if host.startswith(prefix):
        host = host[len(prefix):]
    return 'https://' + host

  def changes_submittable(
      self, gerrit_changes: List[GerritChange],
      test_output_data: Union[Callable, Dict, List, None] = None) -> bool:
    """Check whether the given changes can be merged onto their Git branches.

    Args:
      gerrit_changes: The changes to check.
      test_output_data: Mock response for the git-test-submit support tool.
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
        test_output_data = self.test_api.test_changes_are_submittable
      result = self.m.support.call('git-test-submit', req,
                                   test_output_data=test_output_data)
      if result['errors']:
        presentation.step_text = 'unable to cherry-pick changes'
        presentation.logs['cherry-pick-failures'] = result['errors']
        presentation.status = 'FAILURE'
        presentation.properties['merge_conflict'] = True
        return False

      presentation.step_text = 'confirmed no merge conflicts'
      return True

  def create_change(
      self, project: Union[str, Path], reviewers: Optional[List[str]] = None,
      ccs: Optional[List[str]] = None, topic: Optional[str] = None,
      ref: Optional[str] = None, hashtags: Optional[List[str]] = None,
      project_path: Path = None, use_local_diff: bool = False) -> GerritChange:
    """Create a Gerrit change for the most recent commits in the given project.

    Assumes one or more local commits exists in the project. The commit message
    is always used as the CL description.

    Args:
      project: Any path within the project of interest, or the project name.
      reviewers: List of emails to mark as reviewers on Gerrit.
      ccs: List of emails to mark as cc on Gerrit.
      topic: Topic to set for the CL.
      ref: --target-branch argument to be passed to git cl upload. Should be
        a full git ref, such as 'refs/heads/main' -- NOT just 'main'.
      hashtags: List of hashtags to set for the CL.
      project_path: If set, will use this as the project path rather than any
        value inferred from the gerrit_change.
      use_local_diff: If true, use the local diff instead of diff taken against
        tip-of-branch for the CL.

    Returns:
      The newly created change.
    """
    with self.m.step.nest('create gerrit change for %s' % project) as pres:
      project_info = None
      # Attempt to get project_info. If the project does not exist, we'll assume
      # `project` is the project name and use `project_path` as our cwd.
      # Otherwise, we'll infer the information from the repo.project_info
      # results.
      if self.m.path.exists(self.m.src_state.workspace_path):
        # Need to check that the ChromeOS workspace path exists. In some cases
        # it doesn't, like for StarDoctor. Then we definitely can't get project
        # info.
        with self.m.context(cwd=self.m.src_state.workspace_path):
          if self.m.repo.project_exists(project):
            project_info = self.m.repo.project_info(project)

      if project_path:
        cwd = project_path
      else:
        if not project_info:
          raise StepFailure(
              'project {} does not exist in checkout and `project_path` was not supplied'
              .format(project))
        cwd = self.m.src_state.workspace_path.join(project_info.path)

      with self.m.context(cwd=cwd):
        branch = None
        if ref:
          branch = self.m.git.extract_branch(ref)
          # `branch` needs to exist locally and track the corresponding remote
          # branch, or `git cl` will fail.
          if not self.m.git.branch_exists(branch):
            remote_branch = '{}/{}'.format(self.m.git.remote(), branch)
            self.m.git.create_branch(branch, remote_branch)

        self.m.git_cl.upload(reviewers=reviewers, ccs=ccs, topic=topic,
                             hashtags=hashtags, send_mail=True,
                             target_branch=ref, use_local_diff=use_local_diff)
        issue = None
        if ref:
          # Try to find the issue number for the appropriate branch, which
          # will make `git_cl status` pass with higher probability.
          issue_map = self.m.git_cl.issues()
          if ref in issue_map:
            issue = issue_map[ref]
        gerrit_change_url = self.m.git_cl.status(
            field='url', fast=True, issue=issue,
            step_test_data=functools.partial(
                self.m.raw_io.test_api.stream_output,
                self.test_api.test_gerrit_change_url())).decode()
        pres.links['gerrit change'] = gerrit_change_url

        # The URL does not always include the project name, so always set it.
        change = self.parse_gerrit_change(gerrit_change_url)
        # If there's no project_info (i.e. we're outside of a repo checkout),
        # use the project kwarg as the project name.
        change.project = project_info.name if project_info else project
        return change

  def set_change_labels_remote(self, gerrit_change: GerritChange,
                               labels: Dict[Label, int]) -> str:
    """Set the given labels for the given Gerrit change.

    set_change_labels only works when the change exists in the local checkout.
    This function should be used in other cases.

    Args:
      gerrit_change: The change of interest.
      labels: Mapping from label to value.

    Returns:
      The applied labels (primarily for testing).
    """
    # Convert Labels to strings so they can be easily used outside this module.
    str_labels = {label.key: value for label, value in labels.items()}
    with self.m.step.nest('set labels on CL %d' % gerrit_change.change) as pres:
      pres.logs['labels'] = self.m.json.dumps(str_labels)
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)
      change_num = gerrit_change.change

      return self._do_post(
          f'https://{gerrit_change.host}/changes/{change_num}/revisions/current/review',
          {'labels': str_labels},
          test_output_data=self.m.json.dumps({'labels': str_labels}),
      )

  def add_change_comment_remote(self, gerrit_change: GerritChange,
                                comment: str):
    """Add comment to gerrit_change.

    The comment is left as a resolved patchset level comment.

    Args:
      gerrit_change: The change to comment on.
      comment: The comment to leave.
    """
    with self.m.step.nest(f'add comment on CL {gerrit_change.change}'):
      comment_map = {'/PATCHSET_LEVEL': [{'message': comment}]}
      self._do_post(
          f'https://{gerrit_change.host}/changes/{gerrit_change.change}/revisions/current/review',
          {'comments': comment_map}, test_output_data='{}')

  def _get_auth_token(self) -> Path:
    """Get a token from luci-auth with gerritcodereview scope.

    Gets a token from luci-auth, uses the token to write an authorization header
    to a temp file, and returns a path to this temp file.

    Returns:
      A Path to a temp file containing the authorization header.
    """
    with self.m.step.nest('ensure auth token'):
      auth_token_out = self.m.easy.stdout_step(
          'Retrieve service_account auth token',
          [
              'luci-auth', 'token', '-scopes',
              'https://www.googleapis.com/auth/gerritcodereview',
              '-json-output', '-'
          ],
          test_stdout='{"token": "TEST_TOKEN"}',
      )
      auth_token = self.m.json.loads(auth_token_out)['token']
      auth_token_path = self.m.path.mkstemp(prefix='service_account_auth_token')
      self.m.file.write_text('Write auth token to temp file', auth_token_path,
                             f'Authorization: Bearer {auth_token}',
                             include_log=False)

      return auth_token_path

  @exponential_retry(retries=4, delay=timedelta(seconds=5))
  def _do_post(self, url: str, json_data: Dict[str, Any],
               test_output_data: str) -> str:
    """Send a POST request with json_data to url.

    This method gets a token from luci-auth and includes it in the request.

    Args:
      url: The url to send the request to.
      json_data: A dict to include in the request as JSON.

    Returns:
      The POST response.
    """
    auth_token_path = self._get_auth_token()
    curl_params = [
        '-f', '-X', 'POST', '-H', f'@{auth_token_path}', '-H',
        'Content-Type: application/json', '-d',
        self.m.json.dumps(json_data)
    ]
    data = self.m.easy.stdout_step(f'curl {url}',
                                   ['curl'] + curl_params + [url],
                                   test_stdout=test_output_data)
    return data.decode()

  def set_change_labels(self, gerrit_change: GerritChange,
                        labels: Dict[Label, int], branch: Optional[str] = None,
                        ref: Optional[str] = None) -> str:
    """(Deprecated) Set the given labels for the given Gerrit change.

      This function is deprecated. Use `set_change_labels_remote` where
      possible.

    Args:
      gerrit_change: The change of interest.
      labels: Mapping from label (Label) to value (int).
      branch: The remote branch to update.
      ref: The remote ref to update.

    Returns:
      The ref used to push the labels.
    """
    with self.m.step.nest('set labels on CL %d' % gerrit_change.change) as pres:
      full_labels = sorted(
          ['%s+%d' % (label.key, value) for label, value in labels.items()])
      pres.logs['labels'] = ','.join(full_labels)
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      with self.m.context(cwd=self.m.src_state.workspace_path):
        project_info = self.m.repo.project_info(gerrit_change.project)

      if branch is None:
        branch = project_info.branch.split('/')[-1]
      ref = ref or 'refs/for/%s' % branch
      full_labels_joined = ','.join([f'l={label}' for label in full_labels])
      ref = f'{ref}%{full_labels_joined}'

      if not ref.startswith('HEAD:'):
        ref = 'HEAD:%s' % ref
      with self.m.context(
          cwd=self.m.src_state.workspace_path.join(project_info.path)):
        self.m.git.rebase(force=True)
        self.m.git.push(project_info.remote, ref)
      return ref

  def _get_project_path(self, gerrit_change: GerritChange) -> Path:
    """Return the path of the project associated with the gerrit_change."""
    with self.m.context(cwd=self.m.src_state.workspace_path):
      project_info = self.m.repo.project_info(gerrit_change.project)
    return self.m.src_state.workspace_path.join(project_info.path)

  def add_change_comment(self, gerrit_change: GerritChange, comment: str,
                         project_path: Optional[Path] = None):
    """Add a comment to the given Gerrit change.

    Args:
      gerrit_change: The change to post to.
      comment: The comment to post.
      project_path: If set, will use this as the project path rather than any
        value inferred from the gerrit_change.
    """
    with self.m.step.nest('comment on CL %d' % gerrit_change.change) as pres:
      pres.logs['comment text'] = comment
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      cwd = project_path or self._get_project_path(gerrit_change)
      with self.m.context(cwd=cwd):
        self.m.git_cl('comment', ['-i', gerrit_change.change, '-a', comment])

  def get_change_description(self, gerrit_change: GerritChange,
                             memoize: bool = False) -> str:
    """Get the description of the given Gerrit change.

    Args:
      gerrit_change: The change of interest.
      memoize: Whether to consult a local cache for the change ID instead of
        fetching from gerrit.

    Returns:
      The change description.
    """
    if memoize and gerrit_change.change in self._GET_CHANGE_DESCRIPTION_CACHE:
      return self._GET_CHANGE_DESCRIPTION_CACHE[gerrit_change.change]

    with self.m.step.nest('get CL %d description' %
                          gerrit_change.change) as pres:
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      pres.links['gerrit change'] = gerrit_change_url
      patch_set = self.fetch_patch_sets([gerrit_change],
                                        include_commit_info=True)[0]
      description = typing.cast(str, patch_set.commit_info.get('message'))
      # Make sure that there is a trailing newline.
      description = (
          description if description.endswith('\n') else description + '\n')
      pres.logs['description text'] = description
      if memoize:
        self._GET_CHANGE_DESCRIPTION_CACHE[gerrit_change.change] = description
      return description

  def set_change_description(self, gerrit_change: GerritChange,
                             description: str, amend_local: bool = False,
                             project_path: Optional[Path] = None):
    """Set the description of the given Gerrit change.

    Args:
      gerrit_change: The change of interest.
      description: The new description, in full. Be sure this still includes the
        Change-Id and other essential metadata.
      amend_local: Whether to amend the description of the HEAD local change as
        as well.
      project_path: If set, use this as the project path rather than any value
        inferred from the gerrit_change.
    """
    with self.m.step.nest('set CL %d description' %
                          gerrit_change.change) as pres:
      # Make sure that there is a trailing newline.
      description = (
          description if description.endswith('\n') else description + '\n')
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      pres.links['gerrit change'] = gerrit_change_url
      pres.logs['description text'] = description

      cwd = project_path or self._get_project_path(gerrit_change)
      with self.m.context(cwd=cwd):
        self.m.git_cl.set_description(description, patch_url=gerrit_change_url)
        if amend_local:
          self.m.git.amend_head_message(description)

  def abandon_change(self, gerrit_change: GerritChange,
                     message: Optional[str] = None):
    """Abandon the given change.

    Args:
      gerrit_change: The change to abandon.
      message: Optional message to post to change.
    """
    with self.m.step.nest('abandon CL %d' % gerrit_change.change) as pres:
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      self.m.depot_tools_gerrit.abandon_change(
          self.parse_qualified_gerrit_host(gerrit_change), gerrit_change.change,
          message=message)

  def submit_change(self, gerrit_change: GerritChange, retries: int = 0,
                    project_path: Optional[Path] = None):
    """Submit the given change.

    Args:
      gerrit_change: The change to submit.
      retries: How many times to retry `git cl land` should it fail.
      project_path: If set, use this as the project path rather than any value
        inferred from the gerrit_change.
    """
    with self.m.step.nest('submit CL %d' % gerrit_change.change) as pres:
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      cwd = project_path or self._get_project_path(gerrit_change)
      with self.m.context(cwd=cwd):
        self.m.git_cl('issue', [gerrit_change.change])
        # If retries are requested, attempt `git cl land` until it lands or we
        # run out of tries.
        # TODO(b/278083716): Replace with exponential_retries decorator.
        for attempt in range(retries + 1):
          cmd = self.m.git_cl(
              'land', ['-f', gerrit_change.change], add_output_log=True,
              stderr=self.m.raw_io.output_text(add_output_log=True),
              ok_ret='any')
          # Manually check the retcode so that we can capture stderr and filter
          # out select errors.
          if cmd.retcode == 0:
            return
          # If the change is already merged we've accomplished what we set out
          # to and don't need to raise an error.
          if 'change is merged' in cmd.stderr:
            pres.step_text = 'change is already merged'
            return
          if attempt == retries:
            raise StepFailure('Failed to land change (retcode: %d)' %
                              cmd.retcode)

  def query_changes(self, host: str, query_params: List[Tuple[str, str]],
                    label_constraints: Optional[List[LabelConstraint]] = None
                   ) -> List[GerritChange]:
    """Query gerrit for change meeting certain constraints, and return them.

    Args:
      host: The Gerrit host to query.
      query_params: Query parameters as list of (key, value) tuples to form a
          query, as documented here:
          https://gerrit-review.googlesource.com/Documentation/user-search.html#search-operators
      label_constraints: Constraints on the changes' labels, to be used as a
          filter before returning.
    """
    with self.m.step.nest('query %s' % host) as presentation:
      o_params = ['LABELS'] if label_constraints else None
      results = self.m.depot_tools_gerrit.get_changes(host, query_params,
                                                      o_params=o_params)
      if label_constraints:
        results = [
            r for r in results
            if _do_change_labels_satisfy_constraints(r, label_constraints)
        ]
      changes = [
          change_info_to_gerrit_change(change_info, host)
          for change_info in results
      ]

      presentation.step_text = 'found %d matching CLs' % len(changes)
      for change in changes:
        change_url = self.parse_gerrit_change_url(change)
        presentation.links['found CL %d' % change.change] = change_url

      return changes

  @exponential_retry(retries=4, delay=timedelta(seconds=5))
  @functools.lru_cache
  def get_account_id(
      self,
      email: str,
      gerrit_host: str,
  ) -> int:
    """Get the Gerrit account id for the given email on the given host."""
    auth_token_path = self._get_auth_token()

    # "Get Account" endpoint:
    # https://gerrit-review.googlesource.com/Documentation/rest-api-accounts.html#get-account
    get_url = f'https://{gerrit_host}/accounts/{email}'
    curl_params = ['-f', '-H', f'@{auth_token_path}']

    data = self.m.easy.stdout_step(f'curl {get_url}',
                                   ['curl'] + curl_params + [get_url]).decode()
    data = strip_xssi_prefix(data)

    try:
      result = self.m.json.loads(data)['_account_id']
    except (KeyError, json.JSONDecodeError) as e:
      raise StepFailure(
          f'The response does not contain valid JSON with a "_account_id" key: {data}'
      ) from e

    return result

  @exponential_retry(retries=4, delay=timedelta(seconds=5))
  def get_change_mergeable(self, change_num: int, gerrit_host: str,
                           revision: str = 'current') -> bool:
    """Get the mergeable status of the given Gerrit change.

    Args:
      change_num: The number of the change to check.
      gerrit_host: Base URL to curl against.
      revision: The revision of the change to check.

    Returns:
      Whether the revision of the change is mergeable.
    """
    auth_token_path = self._get_auth_token()

    # "Get Mergeable" endpoint:
    # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#get-mergeable
    get_url = f'https://{gerrit_host}/changes/{change_num}/revisions/{revision}/mergeable'
    curl_params = ['-f', '-H', f'@{auth_token_path}']

    data = self.m.easy.stdout_step(f'curl {get_url}',
                                   ['curl'] + curl_params + [get_url]).decode()
    data = strip_xssi_prefix(data)

    try:
      result = self.m.json.loads(data)['mergeable']
    except (KeyError, json.JSONDecodeError) as e:
      raise StepFailure(
          'The response does not contain valid JSON with a "mergeable" key: %s'
          % data) from e
    if not isinstance(result, bool):
      raise StepFailure(
          f'"mergeable" value is not a bool: {data} (type: {type(result)})')

    return result

  def _ensure_gerrit_related_changes(self):
    """Ensure the gerrit_related_changes cli is installed."""
    with self.m.step.nest('ensure gerrit_related_changes'):
      with self.m.context(infra_steps=True):
        self._related_changes_cipd_package = (
            self._properties.related_changes.related_changes_cipd_package or
            'chromiumos/infra/gerrit_related_changes/${platform}')
        default_ref = 'staging' if self.m.cros_infra_config.is_staging else 'prod'
        self._related_changes_cipd_ref = (
            self._properties.related_changes.related_changes_cipd_ref or
            default_ref)

        cipd_dir = self.m.path['start_dir'].join('cipd')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._related_changes_cipd_package,
                         self._related_changes_cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._related_changes_path = cipd_dir.join('gerrit_related_changes')

  def _call_gerrit_related_changes(self, cmd: List[str],
                                   step_name: Optional[str] = None,
                                   timeout: int = 3600):
    """Call the gerrit_related_changes tool directly.

    Ensure the CIPD package is present.
    """
    self._ensure_gerrit_related_changes()
    self.m.step(step_name or 'gerrit_related_changes',
                [self._related_changes_path] + cmd, timeout=timeout)

  def gerrit_related_changes(self, gerrit_change: GerritChange) -> JSONObject:
    """Fetch and return related changes given a Gerrit change.

    Uses the gerrit_related_changes CIPD package.

    Returns:
      The JSON for 'related' outputted by gerrit_related_changes.
    """
    with self.m.step.nest('call gerrit_related_changes') as presentation:
      messages_path = self.m.path.mkdtemp(prefix='gerrit_related_changes_')
      input_json_file = messages_path.join('input.json')
      output_json_file = messages_path.join('output.json')
      input_json = {'change': gerrit_change.change, 'host': gerrit_change.host}
      self.m.file.write_text('write gerrit_related_changes input',
                             input_json_file, json.dumps(input_json))
      presentation.logs['input_json'] = json.dumps(input_json)
      cmd = [
          'gerrit_related_changes', '--input_json',
          str(input_json_file), '--output_json',
          str(output_json_file)
      ]
      presentation.logs['cmd'] = cmd
      self._call_gerrit_related_changes(cmd)
      # Try except so that the step turns red but does not doom the build.
      try:
        output_json_str = self.m.file.read_text('read output json',
                                                output_json_file,
                                                test_data='{"related":[]}')
        presentation.logs['output_json'] = output_json_str
        output = json.loads(output_json_str)
        related = output.get('related', [])
        return related
      except Exception as e:  #pylint: disable=broad-except
        presentation.step_text = "couldn't parse output of related changes"
        presentation.logs['error'] = str(e)
        return []


def change_info_to_gerrit_change(change_info: ChangeInfo,
                                 host: str) -> GerritChange:
  """Return a GerritChange containing the data from a ChangeInfo."""
  HTTPS = 'https://'
  return GerritChange(
      host=host[len(HTTPS):] if host.startswith(HTTPS) else host,
      project=change_info['project'],
      change=int(change_info['_number']),
  )
