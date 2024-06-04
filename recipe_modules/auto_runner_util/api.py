# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" Helper functions for auto runner recipe."""
import re
from datetime import datetime, timedelta
from typing import List, Tuple, Set
from recipe_engine import recipe_api
from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import AutoRunnerUtilProperties, HostProjects, CLSignalEnum
from RECIPE_MODULES.chromeos.gerrit.api import ChangeInfo
from RECIPE_MODULES.chromeos.gerrit.api import change_info_to_gerrit_change

# Maximum number of changes to query per request.
DEFAULT_MAX_LIMIT_PER_QUERY = 50

# Query parameters for Gerrit API. These are the relevant filters
# for auto runner. See go/run-cq-run for full details and explanations.
# See documentation here
# https://gerrit-review.googlesource.com/Documentation/user-search.html#search-operators
QUERY_PARAMS = (
    ('status', 'open'),
    ('branch', 'main'),
    ('label', 'Bot-Commit<1'),
    ('label', 'Commit-Queue<=0'),
    ('label', 'Code-Review>=0'),
    ('label', 'verified>=0'),
    ('-is', 'wip'),
    ('-age', '1d'),
)
# Query parameters for Gerrit API used to fetch changes to calculate quota usage.
QUERY_PARAMS_FOR_QUOTA_CHECK = (
    ('branch', 'main'),
    ('label', 'Bot-Commit<1'),
    ('-age', '1d'),
)

# Output parameters for Gerrit API.
# See documentation here
# https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#list-changes
O_PARAMS = ('CURRENT_REVISION', 'COMMIT_FOOTERS', 'REVIEWER_UPDATES',
            'DETAILED_ACCOUNTS', 'MESSAGES')

# Output parameters for Gerrit API used to calculate quota usage.
O_PARAMS_FOR_QUOTA_CHECK = (
    'DETAILED_ACCOUNTS',
    'MESSAGES',
)

# Default List of host and project pairs to query.
# This list is used to determine which Gerrit hosts and projects to query for
# changes. The project prefix can be used to match multiple projects. For example,
# project_prefix=['chromeiumos'] query all projects that start with 'chromiumos'.
DEFAULT_HOST_PROJECTS_PREFIXES = [
    HostProjects(host='chromium', project_prefix=['chromiumos']),
    HostProjects(host='chrome-internal', project_prefix=['chromeos']),
]

# The default signal.
DEFAULT_CL_SIGNAL = CLSignalEnum.REVIEWER_ADDED
DEFAULT_DAILY_QUOTA = 50
DEFAULT_DAILY_QUOTA_PER_CL = 5

# TODO: Replace this with real account
AUTO_RUNNER_SERVICE_ACCOUNT_EMAIL = 'PLACEHOLDER_FOR_THE_TIMEBEING@GOOGLE.COM'


class EnhancedChangeInfo():
  """Represents a Gerrit change with additional information.

  This class extends the basic `ChangeInfo` object from the Gerrit API by
  adding methods and properties that are relevant for auto runner, such as:

  - Checking for 'cq-depends' in the commit footer.
  - Checking if the change has reviewers.
  - Retrieving related changes.
  - Counting the number of times the change has been CQed by auto runner in
    the last 24 hours.
  - Checking if the current revision has been CQed once.

  """

  def __init__(self, change: ChangeInfo, host: str, api):
    """Initializes an EnhancedChangeInfo object.

    Args:
        change (ChangeInfo): The ChangeInfo object from the Gerrit API.
        host (str): The Gerrit host.
        api (Any): The recipe_api object providing Gerrit and time functionality.
    """
    self._change_info = change
    self._host = host
    self._gerrit_change_obj = change_info_to_gerrit_change(change, host)
    self._api = api
    self._related_changes = None

  def __eq__(self, other: 'EnhancedChangeInfo') -> bool:
    """Compares two EnhancedChangeInfo objects for equality based on GerritChange object."""
    return self._gerrit_change_obj == other._gerrit_change_obj

  def __lt__(self, other: 'EnhancedChangeInfo') -> bool:
    """Comparison based on recent auto runner CQ count (asc) and updated time (desc).

    Returns:
        bool: True if `self` is less than `other`, False otherwise.
    """
    if (self_count := self.cq_count_from_auto_runner_in_last_day) != (
        other_count := other.cq_count_from_auto_runner_in_last_day):
      return self_count < other_count

    return self._format_datetime(
        self._change_info.get('updated')) > other._format_datetime(
            other._change_info.get('updated'))

  def __hash__(self) -> int:
    """Calculates the hash based on change, host, and project attributes."""
    return hash((self._gerrit_change_obj.change, self._gerrit_change_obj.host,
                 self._gerrit_change_obj.project))

  def _format_datetime(self, date_str: str) -> datetime:
    """Converts a date string to a datetime object.

    Returns:
        datetime: The datetime object parsed from the string.
    """
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S.%f000'
    return datetime.strptime(date_str, DATE_FORMAT)

  def has_cq_depends(self) -> bool:
    """Checks if ChangInfo has 'cq-depends' in its commit footer.

    This function checks if the current revision of the change has 'cq-depends' in
    its commit footer.

    Returns:
      `True` if the change has 'cq-depends' in its commit footer, `False` otherwise.
    """
    revisions = self._change_info.get('revisions', {})

    current_revision = revisions.get(self._change_info.get('current_revision'))
    if current_revision:
      return 'Cq-Depend:' in current_revision.get('commit_with_footers', '')
    return False

  def has_reviewers(self) -> bool:
    """Checks if a Gerrit change has atleast one reviewer.

    Returns:
      `True` if the change has atleast one reviewer, `False` otherwise.
    """
    return any(
        reviewer_update.get('state') == 'REVIEWER'
        for reviewer_update in self._change_info.get('reviewer_updates', []))

  @property
  def change_url(self) -> str:
    """Returns the full URL of the Gerrit change."""
    return self._api.gerrit.parse_gerrit_change_url(self._gerrit_change_obj)

  @property
  def change(self) -> int:
    """Returns the change number of the Gerrit change."""
    return self._gerrit_change_obj.change

  def get_related_changes(self) -> List['EnhancedChangeInfo']:
    """Retrieves and caches related changes as EnhancedChangeInfo objects.

    Returns:
        List[EnhancedChangeInfo]: A list of related changes.
    """
    if not self._related_changes:
      related_changes_obj = self._api.gerrit.gerrit_related_changes(
          self._gerrit_change_obj)
      self._related_changes = [
          EnhancedChangeInfo(
              {
                  '_number': related.get('_change_number'),
                  'project': related.get('project')
              }, related.get('host'), self._api)
          for related in related_changes_obj
      ]
    return self._related_changes

  @property
  def cq_count_from_auto_runner_in_last_day(self) -> int:
    """Counts Commit-Queue+1 messages from auto runner within the last 24 hours.

    Returns:
        int: The count of matching Commit-Queue+1 messages.
    """

    def is_recent_cq_message(msg):
      author = msg.get('author', {})
      return (author.get('email') == AUTO_RUNNER_SERVICE_ACCOUNT_EMAIL and
              'Commit-Queue+1' in msg.get('message', '') and
              self._format_datetime(msg.get('date')) >= cutoff_time)

    now = self._api.time.utcnow()
    cutoff_time = now - timedelta(hours=24)

    return sum(1 for msg in self._change_info.get('messages', [])
               if is_recent_cq_message(msg))

  def has_current_revision_been_cqed_once(self) -> bool:
    """Checks if the current revision has been CQed at least once.

    Returns:
        bool: True if the current revision has been CQed, False otherwise.
    """
    current_revision_number = self._change_info.get('current_revision_number')
    if not current_revision_number:
      return False
    for message in self._change_info.get('messages', []):
      if (message.get('_revision_number', '') == current_revision_number and
          re.search(r'Commit\-Queue\+[12]', message.get('message', ''))):
        return True
    return False


class AutoRunnerUtilApi(recipe_api.RecipeApi):

  def __init__(self, properties: AutoRunnerUtilProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._max_limit_per_query = properties.max_limit_per_query or DEFAULT_MAX_LIMIT_PER_QUERY
    self._host_project_prefixs = properties.host_projects or DEFAULT_HOST_PROJECTS_PREFIXES
    self._cl_signal = properties.cls_signal or DEFAULT_CL_SIGNAL
    self._daily_quota = properties.daily_quota or DEFAULT_DAILY_QUOTA
    self._daily_quota_per_cl = properties.daily_quota_per_cl or DEFAULT_DAILY_QUOTA_PER_CL

  def get_change_infos_from_gerrit(self, host_projects: List[HostProjects],
                                   query_params: Tuple[Tuple[str, str]],
                                   o_params: Tuple[str],
                                   query_limit: int) -> Set[EnhancedChangeInfo]:
    """Retrieves Gerrit change information from configured hosts and projects.

    Args:
        host_projects: List of HostProjects objects defining target hosts and projects.
        query_params: Tuple of tuples specifying Gerrit query parameters (key, value).
        o_params: Tuple of additional Gerrit query options.
        query_limit: Maximum number of results to fetch (None for no limit).

    Returns:
        Set[EnhancedChangeInfo]: A set of EnhancedChangeInfo objects representing the changes.
    """
    all_changes = set()
    for host_project_prefixes in host_projects:
      host = host_project_prefixes.host
      projects = host_project_prefixes.project_prefix
      with self.m.step.nest('Looking for CLs in host %s' % host):
        host_url = 'https://{}-review.googlesource.com'.format(host)
        for project in projects:
          with self.m.step.nest('Looking for CLs in project %s' %
                                project) as project_preso:
            changes_from_project = self.m.gerrit.query_change_infos(
                host_url, query_params + ((
                    'projects',
                    project,
                ),), o_params=list(o_params), limit=query_limit)
            enhanced_changes = {
                EnhancedChangeInfo(change_info, host_url, self.m)
                for change_info in changes_from_project
            }
            all_changes.update(enhanced_changes)
            for change in enhanced_changes:
              project_preso.links['found CL %d' %
                                  change.change] = change.change_url
    return all_changes

  def add_a_step_with_cl_links(self, step_description: str,
                               change_infos: Set[EnhancedChangeInfo]):
    """Adds a recipe step with links to the provided Gerrit changes.

    Args:
        step_description: Description for the recipe step.
        change_infos: A set of EnhancedChangeInfo objects representing the changes.
    """
    with self.m.step.nest(step_description) as preso:
      for change in change_infos:
        preso.links['CL %d' % change.change] = change.change_url

  def get_quota_stats(self) -> int:
    """Calculates the current auto runner quota usage in last 24 hrs.

    Returns: The total number of times auto runner CQed CLs in the last 24 hours.
    """
    with self.m.step.nest('Calculating quota usage thus far'):
      all_changes = self.get_change_infos_from_gerrit(
          self._host_project_prefixs, QUERY_PARAMS_FOR_QUOTA_CHECK,
          O_PARAMS_FOR_QUOTA_CHECK, None)

      return sum(change.cq_count_from_auto_runner_in_last_day
                 for change in all_changes)

  def _filter_changes(self, remaining_changes: Set[EnhancedChangeInfo],
                      step_description: str,
                      filter_func) -> Set[EnhancedChangeInfo]:
    """Filters a set of changes based on the given filter function.

    Args:
        remaining_changes: A set of EnhancedChangeInfo objects to filter.
        step_description: Description for the filtering step.
        filter_func: A function that takes an EnhancedChangeInfo object
                     and returns True if it should be filtered out.

    Returns:
        Set[EnhancedChangeInfo]: A new set containing the filtered changes.
    """
    filtered = {c for c in remaining_changes if filter_func(c)}
    self.add_a_step_with_cl_links(step_description, filtered)
    return remaining_changes - filtered

  def _get_related_changes_set(
      self, changes: Set[EnhancedChangeInfo]) -> Set[EnhancedChangeInfo]:
    """Retrieves all related changes for a given set of changes.

    Args:
        changes: A set of EnhancedChangeInfo objects to find related changes for.

    Returns:
        Set[EnhancedChangeInfo]: A set of all related EnhancedChangeInfo objects.
    """
    with self.m.step.nest('Querying relation chains'):
      return {
          related_change for change in changes
          for related_change in change.get_related_changes()
      }

  def get_eligible_cls(self) -> Set[EnhancedChangeInfo]:
    """Retrieves Gerrit changes that are considered eligible for auto run.

    This function performs the following steps:

    1. Fetches changes from configured Gerrit hosts and projects.
    2. Checks and enforces the daily quota for the auto runner.
    3. Filters out changes that:
        - Have exceeded their individual daily CQ quota.
        - Have already been CQed in their current revision.
        - Contain 'cq-depends' in their commit footer.
        - Lack reviewers (if `_cl_signal` is set to `REVIEWER_ADDED`).
        - Are part of a relation chain with other changes.
    4. Sorts the remaining changes and limits them to the available quota.

    Returns:
        Set[EnhancedChangeInfo]: A set of EnhancedChangeInfos representing the eligible changes.
    """
    total_quota_usage = self.get_quota_stats()
    if total_quota_usage >= self._daily_quota:
      with self.m.step.nest('24 hr Quota exhausted for AutoRunner'):
        return set()

    remaining_changes = self.get_change_infos_from_gerrit(
        self._host_project_prefixs, QUERY_PARAMS, O_PARAMS,
        self._max_limit_per_query)

    # Filter changes that have hit or exceeded their daily quota
    remaining_changes = self._filter_changes(
        remaining_changes,
        'Filtering CLs that have exhausted their daily quota', lambda c: c.
        cq_count_from_auto_runner_in_last_day >= self._daily_quota_per_cl)

    # Filter changes that have already been CQed in their current revision
    remaining_changes = self._filter_changes(
        remaining_changes,
        'Filtering CLs whose current patchset has already had a cq run',
        lambda c: c.has_current_revision_been_cqed_once())

    # Filter changes that contain 'cq-depends' in their commit footer
    remaining_changes = self._filter_changes(
        remaining_changes, 'Filtering CLs that have cq-depends',
        lambda c: c.has_cq_depends())

    # Filter changes that lack reviewers
    if self._cl_signal == CLSignalEnum.REVIEWER_ADDED:
      remaining_changes = self._filter_changes(
          remaining_changes, 'Filtering CLs that do not have any reviewers',
          lambda c: not c.has_reviewers())

    # Filter changes that are part of a relation chain with other changes
    related_changes = self._get_related_changes_set(remaining_changes)
    remaining_changes = self._filter_changes(
        remaining_changes, 'Filtering CLs that are in relation chain',
        lambda c: c in related_changes)

    # Sort the remaining changes and limit them to the available quota
    self.add_a_step_with_cl_links('Remaining eligible CLs', remaining_changes)
    remaining_quota = self._daily_quota - total_quota_usage
    if remaining_changes:
      remaining_changes = sorted(remaining_changes)
    return set(list(remaining_changes)[:remaining_quota])
