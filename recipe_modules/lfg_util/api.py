# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility functions for looks for green."""

from typing import List
from datetime import datetime
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
                GerritChange(host=host_url, change=int(change_id),
                             project=change.project))

      pres.logs['bad_footers'] = '\n'.join(log_lines)
      if not not_included_changes:
        pres.step_text = 'all depended CLs are included'
      else:
        pres.logs['not_included_changes'] = '\n'.join(
            [str(c) for c in not_included_changes])
      return not_included_changes

  def latest_submitted_time(self, gerrit_changes: List[GerritChange],
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
      rev_info = self.m.gerrit.get_revision_info(host=repo_url,
                                                 change=change.change,
                                                 patchset=change.patchset,
                                                 step_test_data=step_test_data)
      submit_string = rev_info.get('submitted', None)
      if submit_string is None:
        return None
      submitted_times.append(datetime.strptime(submit_string, DATETIME_FORMAT))

    return max(submitted_times)
