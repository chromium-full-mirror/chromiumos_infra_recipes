# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" Helper functions for auto runner recipe."""

from typing import Dict, List, Tuple
from recipe_engine import recipe_api
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from RECIPE_MODULES.chromeos.gerrit.api import ChangeInfo, JSONObject
from RECIPE_MODULES.chromeos.gerrit.api import change_info_to_gerrit_change

# Maximum number of changes to query per request.
MAX_LIMIT_PER_QUERY = 50

# Query parameters for Gerrit API. These are the relevant filters
# for auto runner. See go/run-cq-run for full details and explanations.
# See documentation here
# https://gerrit-review.googlesource.com/Documentation/user-search.html#search-operators
QUERY_PARAMS = (
    ('status', 'open'),
    ('label', 'Commit-Queue<=0'),
    ('label', 'Code-Review>=0'),
    ('label', 'verified>=0'),
    ('-is', 'wip'),
)

# Output parameters for Gerrit API.
# See documentation here
# https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#list-changes
O_PARAMS = ('CURRENT_REVISION', 'COMMIT_FOOTERS')

# Gerrit hosts to query. These are the relevant hosts for chromeos.
HOSTS = ('chromium', 'chrome-internal')

# Gerrit projects prefix to query.
PROJECTS_PREFIX = ('chromiumos', 'chromeos')


class AutoRunnerUtilApi(recipe_api.RecipeApi):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def _get_unrelated_changes(
      self, all_current_changes: List[GerritChange],
      all_related_changes: List[GerritChange]) -> List[GerritChange]:
    """
    Filters out Gerrit changes from that are present in `all_related_changes`

    This function is used to identify changes within `all_current_changes`
    that do not have a corresponding match within `all_related_changes`.
    The comparison is based on the project, host, and change number attributes
    of each `GerritChange` object.

    Returns:
        A list of `GerritChange` objects representing the changes found in
        `all_current_changes` that are not present in `all_related_changes`.
    """
    return [
        cl for cl in all_current_changes
        if not any(cl.project == rc.project and cl.host == rc.host and
                   str(cl.change) == str(rc.change)
                   for rc in all_related_changes)
    ]

  def _get_gerrit_changes_from_json_obj(
      self, json_obj_list: List[JSONObject]) -> List[GerritChange]:
    """Converts a list of Gerrit change JSON objects to a list of GerritChange objects.

    Args:
      json_obj_list: A list of JSON objects representing Gerrit changes.

    Returns:
      A list of `GerritChange` objects.
    """
    return [
        GerritChange(
            project=related.get('project'), host=related.get('host'),
            change=related.get('_change_number')) for related in json_obj_list
    ]

  def filter_related_changes(
      self, all_gerrit_changes: List[GerritChange]) -> List[GerritChange]:
    """Removes changes that are part of relation chain.

    This function takes a list of `GerritChange` objects as input and
    filters out changes that are part of a relation chain.

    Args:
      all_changes: A list of `GerritChange` objects.

    Returns:
      A list of `GerritChange` objects representing the changes that are not
      in relation chain.
    """

    related_changes_so_far = []
    with self.m.step.nest('Filtering Related Chain CLs') as preso:
      for change in all_gerrit_changes:
        if change not in related_changes_so_far:
          related_changes_obj = self.m.gerrit.gerrit_related_changes(change)
          related_changes_so_far.extend(
              self._get_gerrit_changes_from_json_obj(related_changes_obj))
      for change in related_changes_so_far:
        change_url = self.m.gerrit.parse_gerrit_change_url(change)
        preso.links['Filtering CL %d' % change.change] = change_url

      return self._get_unrelated_changes(all_gerrit_changes,
                                         related_changes_so_far)

  def _has_cq_depends(self, change_info: ChangeInfo) -> bool:
    """Checks if a Gerrit change has 'cq-depends' in its commit footer.

    This function takes a `ChangeInfo` object as input and determines if the
    current revision of the change has 'cq-depends' in its commit footer.
    It returns `True` if 'cq-depends' is present, and `False` otherwise.

    Args:
      change_info: A `ChangeInfo` object representing the Gerrit change.

    Returns:
      `True` if the change has 'cq-depends' in its commit footer, `False` otherwise.
    """

    revisions = change_info.get('revisions')
    if not revisions:
      return False

    current_revision_number = change_info.get('current_revision_number')
    if not current_revision_number:
      return False

    # Check if the current revision contains 'cq-depends'
    for revision in revisions.values():
      if (revision.get('_number') == current_revision_number and
          'Cq-Depend:' in revision.get('commit_with_footers', {})):
        return True

    return False

  def filter_dependent_changes(
      self,
      change_infos: Dict[str, List[ChangeInfo]]) -> Dict[str, List[ChangeInfo]]:
    """Filters out Gerrit changes that have 'cq-depends' in their commit footer.

    This function takes a dictionary of Gerrit change information, where the keys
    are Gerrit host URLs and the values are lists of `ChangeInfo` objects. It
    then filters out changes that have 'cq-depends' in their commit footer.

    Args:
      change_infos: A dictionary of Gerrit change information, where the keys
        are Gerrit host URLs and the values are lists of `ChangeInfo` objects.

    Returns:
      A dictionary of Gerrit change information, where the keys are Gerrit host
      URLs and the values are lists of `ChangeInfo` objects that do not have
      'cq-depends' in their commit footer.
    """
    no_cq_depend_change_infos = {}
    with self.m.step.nest('Filtering Cq-Depend CLs'):
      for host_url, change_infos_per_host in change_infos.items():
        with self.m.step.nest('Filtering CQ-Depend CLs for host %s' %
                              host_url) as host_preso:
          remaining_change = []
          for change_info in change_infos_per_host:
            if not self._has_cq_depends(change_info):
              remaining_change.append(change_info)
            else:
              host_preso.links[
                  'Filtering CL %s' %
                  change_info.get('_number')] = host_url + '/' + str(
                      change_info.get('_number'))
        no_cq_depend_change_infos[host_url] = remaining_change
    return no_cq_depend_change_infos

  def get_change_infos_from_gerrit(
      self, hosts: Tuple[str], projects: Tuple[str],
      query_params: Tuple[Tuple[str, str]],
      o_params: Tuple[str]) -> Dict[str, List[ChangeInfo]]:
    """Retrieves Gerrit change information from all configured hosts and projects.

    This function retrieves Gerrit change information from all configured hosts
    and projects that match the constraints specified in `QUERY_PARAMS`. It
    users the Gerrit API to query for changes that meet the specified criteria.

    Returns:
      A dictionary of Gerrit change information, where the keys are Gerrit host
      URLs and the values are lists of `ChangeInfo` objects.
    """
    all_changes = {}
    for host in hosts:
      with self.m.step.nest('Looking for CLs in host %s' % host):
        host_url = 'https://{}-review.googlesource.com'.format(host)
        changes = []
        for project in projects:
          with self.m.step.nest('Looking for CLs in project %s' %
                                project) as project_preso:
            changes_from_project = self.m.gerrit.query_change_infos(
                host_url, query_params + ((
                    'projects',
                    project,
                ),), o_params=list(o_params), limit=MAX_LIMIT_PER_QUERY)
            changes.extend(changes_from_project)
            for change in changes_from_project:
              gerrit_change = change_info_to_gerrit_change(change, host_url)
              change_url = self.m.gerrit.parse_gerrit_change_url(gerrit_change)
              project_preso.links['found CL %d' %
                                  gerrit_change.change] = change_url
        all_changes[host_url] = changes
    return all_changes

  def get_eligible_cls(self) -> List[GerritChange]:
    """Retrieves Gerrit changes that are considered eligible for auto run.

    This function performs the following steps:

    1. Retrieves Gerrit change information from all configured hosts and projects
       that matches the constraints mentieond in `QUERY_PARAMS`.
    2. Filters out changes that have 'cq-depends' in their commit footer.
    3. Filters out changes that are part of a relation chain.

    Returns:
      A list of `GerritChange` objects representing the eligible Gerrit changes.
    """
    all_changes = self.get_change_infos_from_gerrit(HOSTS, PROJECTS_PREFIX,
                                                    QUERY_PARAMS, O_PARAMS)

    no_cq_dependent_change_infos = self.filter_dependent_changes(all_changes)
    no_cq_dependent_gerrit_changes = [
        change_info_to_gerrit_change(change_info, host)
        for host, change_infos in no_cq_dependent_change_infos.items()
        for change_info in change_infos
    ]
    remaining_cls = self.filter_related_changes(no_cq_dependent_gerrit_changes)
    return remaining_cls
