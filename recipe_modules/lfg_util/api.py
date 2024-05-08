# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility functions for looks for green."""

from collections import OrderedDict
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
            gerrit_changes=[change], key='Cq-Depend',
            step_test_data=self.m.git_footers.test_api.step_test_data_factory(
                ''))
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

  def get_parent_changes(self, merge_commit_cls: List[GerritChange],
                         step_test_data=None) -> List[GerritChange]:
    """Retrieve the changes corresponding to the parent commits.

    Args:
      merge_commit_cls: merge commit changes to find parents of.

    Returns:
      submitted changes corresponding to the parent commits of input changes.
    """
    parent_changes = []
    with self.m.step.nest('get parent commits of merge CLs') as pres:
      for change in merge_commit_cls:
        host_url = 'https://{}'.format(change.host)
        change_info = self.m.depot_tools_gerrit.get_changes(
            host_url, query_params=[('change', str(change.change))],
            o_params=['CURRENT_REVISION', 'ALL_COMMITS',
                      'PARENTS'], step_test_data=step_test_data)[0]
        pres.logs['change_info #{}'.format(change.change)] = str(change_info)
        for _, rev_info in change_info['revisions'].items():
          for parent_info in rev_info['parents_data']:
            # If 'change_id' is not present, assume the parent is outside of CrOS tree.
            if 'change_id' in parent_info:
              parent_changes.append(
                  GerritChange(host=change.host, project=change.project,
                               change=parent_info['change_number'],
                               patchset=parent_info['patch_set_number']))

    return parent_changes

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
      change_info = self.m.depot_tools_gerrit.get_changes(
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

  def get_depended_cls(
      self, gerrit_changes: List[GerritChange]) -> List[GerritChange]:
    """Gets the depended CLs for the given list of changes.

    Note that the depended CLs returned are ones that are not included in the
    CQ run for the given list of changes.

    Args:
      gerrit_changes: Gerrit changes to analyze.

    Returns:
      List of depended Gerrit changes.
    """
    not_included_cq_depend_cls = self.not_included_cq_depend_cls(gerrit_changes)

    merge_commit_cls = [
        c for c in gerrit_changes
        if self.m.gerrit.is_merge_commit(c.change, c.host)
    ]
    merge_parent_changes = self.get_parent_changes(merge_commit_cls)

    to_apply = OrderedDict()
    with self.m.failures.ignore_exceptions(), self.m.step.nest(
        'find related CLs') as pres:
      all_related_changes = OrderedDict()
      for change in gerrit_changes:
        # Note: this might include duplicates.
        all_related_changes[
            change.change] = self.m.gerrit.gerrit_related_changes(change)
      pres.logs['related_changes'] = str(all_related_changes)
      to_apply = self.m.cros_source.related_changes_to_apply(
          gerrit_changes, all_related_changes)
      self.m.easy.set_properties_step(related_changes_to_apply=to_apply)

    return (not_included_cq_depend_cls + self.json_to_gerritchanges(to_apply) +
            merge_parent_changes)
