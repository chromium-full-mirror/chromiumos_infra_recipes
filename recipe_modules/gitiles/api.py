# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for dealing with Gitiles."""

from recipe_engine import recipe_api


class GitilesApi(recipe_api.RecipeApi):
  """A module for Gitiles helpers."""

  def fetch_revision(self, host, project, branch, test_output_data=None):
    """Call gitiles-fetch-ref support tool.

    Args:
      host (str): Gerrit host, e.g. chrome-internal
      project (str): Gerrit project, e.g. chromiumos/chromite
      branch (str): Gerrit branch, e.g. master
      test_output_data (dict): Test output for gitiles-fetch-ref.

    Returns:
      str: the current revision hash of the specified branch
    """
    if test_output_data is None:
      test_output_data = self.test_api.test_fetch_revision_output()
    # Allow the caller to pass in a ref to the branch, instead of the branch
    # name.
    if branch.startswith('refs/heads/'):
      branch = branch[len('refs/heads/'):]
    input = {
        'branch': {
            'host': host,
            'project': project,
            'branch': branch,
        },
    }
    res = self.m.support.call('gitiles-fetch-ref', input,
                              test_output_data=test_output_data)
    return res['branch']['revision']

  def repo_url(self, commit):
    """Return the url for the repo in a GitilesCommit.

    Args:
      commit (GitilesCommit): The gitiles commit to use.

    Returns:
      (str) The url for the repo.
    """
    return 'https://%s/%s' % (commit.host, commit.project)

  def file_url(self, commit, file_path=None):
    """Return the url for a file in a GitilesCommit.

    Args:
      commit (GitilesCommit): The gitiles commit to use.
      file_path (str): The file path to append, if any.

    Returns:
      (str) The url for the file.
    """
    ref = commit.id or commit.ref
    return '%s/+/%s/%s' % (self.repo_url(commit), ref, file_path or '')
