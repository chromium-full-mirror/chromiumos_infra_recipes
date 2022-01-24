# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for managing Gerrit changes."""

from datetime import timedelta
import enum
import functools
import re

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine.recipe_api import RecipeApi, StepFailure
from RECIPE_MODULES.chromeos.util.util import exponential_retry

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
    self._patch_set = self._rev_info.get('_number', 0)

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
    self._gerrit_patch_sets = None
    self._GET_CHANGE_DESCRIPTION_CACHE = {}

  @property
  def gerrit_patch_sets(self):
    """The gerrit patches last fetched.

    These may or may not include files, but always include commit info.
    """
    if self._gerrit_patch_sets is None:
      self.fetch_patch_sets(self.m.src_state.gerrit_changes,
                            include_commit_info=True)
    return self._gerrit_patch_sets

  def _gerrit_fetch_changes(self, request, gerrit_changes,
                            test_output_data=None):
    """Call gerrit-fetch-changes support tool.

    Args:
      request (dict): Input data.
      test_output_data (dict): Test output for gerrit-fetch-changes.

    Returns:
      dict: Output data.
    """
    if test_output_data is None:
      test_output_data = lambda: self.test_api.test_gerrit_fetch_changes(
          request, gerrit_changes)
    return self.m.support.call('gerrit-fetch-changes', request,
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
    if include_commit_info:
      self._gerrit_patch_sets = patch_sets
    return patch_sets

  def fetch_patch_set_from_change(self, change, include_files=False,
                                  test_output_data=None):
    """Fetch and return PatchSet associated with the given GerritChange.

    Assumes that change.patchset is set (which is not always the case).
    The step fails if the specific patch set is not found.

    Args:
      gerrit_changes (GerritChange): Buildbucket GerritChange to fetch.
      include_files (bool): If True, include information about changed files.
      test_output_data (dict): Test output for gerrit-fetch-changes.

    Returns:
      PatchSet: The corresponding PatchSet.
    """
    patch_sets = self.fetch_patch_sets([change], include_files=include_files,
                                       test_output_data=test_output_data)
    patch_sets = [x for x in patch_sets if x.patch_set == change.patchset]
    if not patch_sets:
      raise StepFailure('missing gerrit patch')
    return patch_sets[0]

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
        test_output_data = self.test_api.test_changes_are_submittable
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
                    ref=None, hashtags=None, project_path=None):
    """Create a Gerrit change for the most recent commits in the given project.

    Assumes one or more local commits exists in the project. The commit message
    is always used as the CL description.

    Args:
      project (str|Path): Any path within the project of interest, or the
        project name.
      reviewers (list[str]): List of reviewer emails. If specified, gerrit will
          email the reviewers.
      ccs (list[str]): List of cc emails. If specified, gerrit will cc the
          individuals.
      topic (str): Topic to set for the CL.
      ref: --target-branch argument to be passed to git cl upload. Should be
        a full git ref, e.g. refs/heads/main (NOT just 'main').
      hashtags (list[str]): List of hashtags to set for the CL.
      project_path (Path): If set, will use this as the project path rather than
        any value inferred from the gerrit_change.

    Returns:
      GerritChange: The newly created change.
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
                             target_branch=ref)
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
                self.test_api.test_gerrit_change_url()))
        pres.links['gerrit change'] = gerrit_change_url

        # The URL does not always include the project name, so always set it.
        change = self.parse_gerrit_change(gerrit_change_url)
        # If there's no project_info (i.e. we're outside of a repo checkout),
        # use the project kwarg as the project name.
        change.project = project_info.name if project_info else project
        return change

  def set_change_labels_remote(self, gerrit_change, labels):
    """Set the given labels for the given Gerrit change.
      set_change_labels only works when the change exists in the local checkout.
      This function should be used in other cases.

    Args:
      gerrit_change (GerritChange): The change of interest.
      labels (dict): Mapping from label (Label) to value (int).

    Returns:
      str: The applied labels (primarily for testing).
    """
    # Convert Labels to strs so labels can be easily used outside of gerrit module
    labels = {label.key: value for label, value in labels.items()}
    with self.m.step.nest('set labels on CL %d' % gerrit_change.change) as pres:
      pres.logs['labels'] = self.m.json.dumps(labels)
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)
      change_num = gerrit_change.change

      applied_labels = self._do_set_change_labels(change_num, labels,
                                                  gerrit_change.host)
      return applied_labels

  @exponential_retry(retries=5, delay=timedelta(seconds=5))
  def _do_set_change_labels(self, change_num, labels, gerrit_host,
                            test_output_data=None):
    """Set the labels on a gerrit change using Gerrit and Gitiles REST API.

    Args:
      change_num (int): The number of the change to label.
      labels (dict): Mapping from label (Label) to value (int).
      gerrit_host (str): Base URL to curl against.
      credential_cookie_location (str): Path to git credential cookie.
      test_output_data (dict): Test output for set_change_labels.

    Returns:
      str: JSON containing the applied labels (primarily for testing).
    """
    post_url = 'https://%s/changes/%s/revisions/current/review' % (gerrit_host,
                                                                   change_num)
    post_json = {'labels': labels}

    # Retrieve the service_account user's auth token.
    auth_token_out = self.m.easy.stdout_step(
        'Retrieve service_account auth token', [
            'luci-auth', 'token', '-scopes',
            'https://www.googleapis.com/auth/gerritcodereview', '-json-output',
            '-'
        ], ok_ret={0}, test_stdout='{"token": "TEST_TOKEN"}')
    auth_token = self.m.json.loads(auth_token_out)['token']
    auth_token_path = self.m.path.mkstemp(prefix='service_account_auth_token')
    self.m.file.write_text('Write auth token to temp file', auth_token_path,
                           'Authorization: Bearer %s' % auth_token,
                           include_log=False)

    curl_params = [
        '-f', '-X', 'POST', '-H',
        '@%s' % auth_token_path, '-H', 'Content-Type: application/json', '-d',
        self.m.json.dumps(post_json)
    ]
    test_output_data = test_output_data or self.m.json.dumps(post_json)

    post_json = {'labels': labels}
    data = self.m.easy.stdout_step('curl %s' % post_url,
                                   ['curl'] + curl_params + [post_url],
                                   ok_ret={0}, test_stdout=test_output_data)
    return data

  def set_change_labels(self, gerrit_change, labels, branch=None, ref=None):
    """(Deprecated) Set the given labels for the given Gerrit change.

      This function is deprecated. Use `set_change_labels_remote` where
      possible.

    Args:
      gerrit_change (GerritChange): The change of interest.
      labels (dict): Mapping from label (Label) to value (int).
      branch (str): The remote branch to update.
      ref (str): The remote ref to update.

    Returns:
      str: The refspec used to push the labels.
    """
    with self.m.step.nest('set labels on CL %d' % gerrit_change.change) as pres:
      full_labels = sorted(
          ['%s+%d' % (label.key, value) for label, value in labels.iteritems()])
      pres.logs['labels'] = ','.join(full_labels)
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      with self.m.context(cwd=self.m.src_state.workspace_path):
        project_info = self.m.repo.project_info(gerrit_change.project)

      if branch is None:
        branch = project_info.branch.split('/')[-1]
      ref = ref or 'refs/for/%s' % branch
      ref = '%s%%%s' % (ref, ','.join(['l=%s' % label for label in full_labels
                                      ]))

      if not ref.startswith('HEAD:'):
        ref = 'HEAD:%s' % ref
      with self.m.context(
          cwd=self.m.src_state.workspace_path.join(project_info.path)):
        self.m.git.rebase(force=True)
        self.m.git.push(project_info.remote, ref)
      return ref

  def _get_project_path(self, gerrit_change):
    """Return the path of the project associated with the given gerrit_change.

    Args:
      gerrit_change (GerritChange): The change of interest.

    Returns:
      Path: The path of the project.
    """
    with self.m.context(cwd=self.m.src_state.workspace_path):
      project_info = self.m.repo.project_info(gerrit_change.project)

    return self.m.src_state.workspace_path.join(project_info.path)

  def add_change_comment(self, gerrit_change, comment, project_path=None):
    """Add a comment to the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change to post to.
      comment (str): The comment to post.
      project_path (Path): If set, will use this as the project path rather than
        any value inferred from the gerrit_change.

    Returns:
      str: The new message ref (primarily for testing).
    """
    with self.m.step.nest('comment on CL %d' % gerrit_change.change) as pres:
      pres.logs['comment text'] = [comment]
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      cwd = project_path or self._get_project_path(gerrit_change)
      with self.m.context(cwd=cwd):
        self.m.git_cl('comment', ['-i', gerrit_change.change, '-a', comment])

  def get_change_description(self, gerrit_change, memoize=False):
    """Get the description of the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      memoize (bool): Should we consult a local cache for the change id instead
          of fetching from gerrit.
    Returns:
      str: The change description.
    """
    if memoize and gerrit_change.change in self._GET_CHANGE_DESCRIPTION_CACHE:
      return self._GET_CHANGE_DESCRIPTION_CACHE[gerrit_change.change]

    with self.m.step.nest('get CL %d description' %
                          gerrit_change.change) as pres:
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      pres.links['gerrit change'] = gerrit_change_url
      patch_set = self.fetch_patch_sets([gerrit_change],
                                        include_commit_info=True)[0]
      description = patch_set.commit_info.get('message')
      # Make sure that there is a trailing newline.
      description = (
          description if description.endswith('\n') else description + '\n')
      pres.logs['description text'] = [description]
      if memoize:
        self._GET_CHANGE_DESCRIPTION_CACHE[gerrit_change.change] = description
      return description

  def set_change_description(self, gerrit_change, description,
                             amend_local=False, project_path=None):
    """Set the description of the given Gerrit change.

    Args:
      gerrit_change (GerritChange): The change of interest.
      description (str): The new description, in full. Be sure this still
          includes the Change-Id and other essential metadata.
      amend_local (bool): Should you amend the description of the HEAD local
          change as well.
      project_path (Path): If set, will use this as the project path rather than
        any value inferred from the gerrit_change.

    """
    with self.m.step.nest('set CL %d description' %
                          gerrit_change.change) as pres:
      # Make sure that there is a trailing newline.
      description = (
          description if description.endswith('\n') else description + '\n')
      gerrit_change_url = self.parse_gerrit_change_url(gerrit_change)
      pres.links['gerrit change'] = gerrit_change_url
      pres.logs['description text'] = [description]

      cwd = project_path or self._get_project_path(gerrit_change)
      with self.m.context(cwd=cwd):
        self.m.git_cl.set_description(description, patch_url=gerrit_change_url)
        if amend_local:
          self.m.git.amend_head_message(description)

  def abandon_change(self, gerrit_change, message=None):
    """Abandon the given change.

    Args:
      gerrit_change (GerritChange): The change to abandon.
      message (str): Optional message to post to change.
    """
    with self.m.step.nest('abandon CL %d' % gerrit_change.change) as pres:
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      self.m.depot_tools_gerrit.abandon_change(
          self.parse_qualified_gerrit_host(gerrit_change), gerrit_change.change,
          message=message)

  def submit_change(self, gerrit_change, retries=0, project_path=None):
    """Submits the given change.

    Args:
      gerrit_change (GerritChange): The change to submit.
      retries (int): How many times to retry `git cl land` should it fail.
      project_path (Path): If set, will use this as the project path rather than
        any value inferred from the gerrit_change.

    """
    with self.m.step.nest('submit CL %d' % gerrit_change.change) as pres:
      pres.links['gerrit change'] = self.parse_gerrit_change_url(gerrit_change)

      cwd = project_path or self._get_project_path(gerrit_change)
      with self.m.context(cwd=cwd):
        self.m.git_cl('issue', [gerrit_change.change])
        # If retries are requested, attempt `git cl land` until it lands or we
        # run out of tries.
        for attempt in range(retries + 1):
          try:
            self.m.git_cl('land', ['-f', gerrit_change.change])
            return
          except StepFailure as ex:
            if attempt == retries:
              raise ex

  def query_changes(self, host, query_params):
    """Query gerrit for the given changes.

    Args:
      host (str): The Gerrit host to query.
      query_params (list[(str, str)]): Query parameters as list of (key, value)
          tuples to form a query as documented here:
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
