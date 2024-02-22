# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility functions for looks for green."""

from typing import Dict, List
from datetime import datetime, timezone
from recipe_engine import recipe_api
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

HOST_SUFFIX = '-review.googlesource.com'
ALLOWED_HOSTS = ['chromium', 'chrome-internal']
DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'


class LFGUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with LFG."""

  def not_included_cq_depend_cls(
      self, gerrit_changes: List[GerritChange]) -> List[GerritChange]:
    """Find the CQ-Depended changes that are not included in this run.

    Args:
      gerrit_changes: Gerrit changes included in this CQ run.

    Returns:
      List of changes that input CLs CQ-depend on but are not included in this run.
    """
    not_included_changes = []
    with self.m.step.nest('check if all Cq-Depend CLs are included') as pres:
      changes_included = set(
          (change.host, change.change) for change in gerrit_changes)
      log_lines = []
      for change in gerrit_changes:
        git_footer_values = self.m.git_footers.get_footer_values(
            gerrit_changes=[change], key='Cq-Depend')
        for footer in git_footer_values:
          if ':' not in footer:
            if not footer.isnumeric():
              # Malformed footer
              log_lines.append('Could not resolve {} footer.'.format(footer))
              continue
            # Users can specify 'Cq-Depend: 12345678'. Host should be inferred from
            # the current change.
            change_id = footer
            # Remove HOST_SUFFIX.
            host = change.host[:-len(HOST_SUFFIX)]
          else:
            [host, change_id] = footer.split(':')
          if change_id == '' or host == '' or host not in ALLOWED_HOSTS:
            # Malformed footer
            log_lines.append('Could not resolve {} footer.'.format(footer))
            continue
          host_url = '{}{}'.format(host, HOST_SUFFIX)
          if (host_url, int(change_id)) not in changes_included:
            pres.step_text = 'cq-depended cl(s) not included in the run'
            not_included_changes.append(
                GerritChange(host=host_url, project=change.project,
                             change=int(change_id), patchset=1))

      pres.logs['bad_footers'] = '\n'.join(log_lines)
      if not not_included_changes:
        pres.step_text = 'all depended CLs are included'
      else:
        pres.logs['not_included_changes'] = '\n'.join(
            [str(c) for c in not_included_changes])
      return not_included_changes

  def latest_submission_time(self, gerrit_changes: List[GerritChange],
                             step_test_data=None) -> datetime:
    """Find the last submitted change and return the submit time.

    Args:
      gerrit_changes: Gerrit changes to analyze.

    Returns:
      Submit time of the last submitted change among the inputs, None
      if one of them hasn't submitted yet.
    """
    submitted_times = []
    for change in gerrit_changes:
      repo_url = 'https://{}/{}'.format(change.host, change.project)
      change_info = self.m.gerrit.get_changes(
          host=repo_url, query_params=[('change', str(change.change))],
          o_params=['ALL_REVISIONS',
                    'ALL_COMMITS'], limit=1, step_test_data=step_test_data)
      submit_string = change_info[0].get('submitted',
                                         None) if change_info else None
      if submit_string is None:
        return None
      # Truncate the last three chars from submit_string. Gerrit specifies
      # time in nanoseconds but strptime can only handle until microseconds.
      submit_time = datetime.strptime(submit_string[:-3], DATETIME_FORMAT)
      submit_time.replace(tzinfo=timezone.utc)
      submitted_times.append(submit_time)

    return max(submitted_times)

  def json_to_gerritchanges(self, changes_dict: Dict) -> List[GerritChange]:
    """Create GerritChange objects from JSON objects return from GerritAPI.

    Args:
      changes_dict: A map of gerrit_change in this run to the changes that they
          related on the stack.

    Returns:
      List the related changes in the proto format.
    """
    gerrit_changes = []
    if changes_dict:
      for _, related_changes in changes_dict.items():
        for change in related_changes:
          gerrit_changes.append(
              GerritChange(host=change['host'], project=change['project'],
                           change=change['_change_number'],
                           patchset=change['_revision_number']))

    return gerrit_changes
