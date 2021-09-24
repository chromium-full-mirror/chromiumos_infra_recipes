# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for dealing with Gitiles."""

from future.standard_library import install_aliases
install_aliases()

import base64
# pylint: disable=no-name-in-module
from urllib.parse import urlunparse

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class GitilesApi(recipe_api.RecipeApi):
  """A module for Gitiles helpers."""

  def fetch_revision(self, host, project, branch, test_output_data=None):
    """Call gitiles-fetch-ref support tool.

    Args:
      host (str): Gerrit host, e.g. 'chrome-internal'.
      project (str): Gerrit project, e.g. 'chromiumos/chromite'.
      branch (str): Gerrit branch, e.g. 'main'.
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
    gitiles_input = {
        'branch': {
            'host': host,
            'project': project,
            'branch': branch,
        },
    }
    res = self.m.support.call('gitiles-fetch-ref', gitiles_input,
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

  def get_file(self, host, project, path, ref=None, public=True,
               credential_cookie_location=None, test_output_data=None):
    """Return the contents of a file hosted on Gitiles.

    Curl will return a zero exit status on many occasions if the server
    responded even if the response isn't what you expected. When this succeeds
    the server returns base64, so not being able to decode this is a good
    indication something is wrong.

    Args:
      host (str): Gerrit host, e.g. chrome-internal.googlesource.com.
      project (str): Gerrit project, e.g. chromiumos/chromite.
      path: (str): The path to the file e.g. api/controller/something.py.
      ref: (str): The ref you should return the file from, default: HEAD.
      public: (bool): If False, will look in .git-credential-cache for an
          authorization cookie and use it in the curl. Default: True.
      credential_cookie_location: (str): The credential cookie location.
          Default: '~/.git-credential-cache/cookie'.
      test_output_data (str): Test output for curl.

    Returns:
      (str) The contents of the file as a string or raise StepFailure on
          unexpected curl return.
    """
    test_output_data = test_output_data or self._test_data.get('get_file')
    credential_cookie_location = (
        credential_cookie_location or
        self.m.path.join(self.m.path['home'], '.git-credential-cache/cookie'))
    cred_cache_cmd = [] if public else ['-b', credential_cookie_location]
    ref = ref or 'HEAD'
    file_url_part = '/'.join((project, '+', ref, path))
    url = urlunparse(('https', host, file_url_part, '', 'format=TEXT', ''))
    with self.m.step.nest('fetch gitiles file') as pres:
      data = self.m.easy.stdout_step('curl %s' % url,
                                     ['curl'] + cred_cache_cmd + [url],
                                     ok_ret={0}, test_stdout=test_output_data)
      try:
        decoded_data = base64.b64decode(data)
      except TypeError:
        raise StepFailure('non base64 data returned from gitiles')
      pres.logs['data'] = decoded_data
      return decoded_data

  def set_change_labels(self, change_num, labels, gerrit_host,
                        credential_cookie_location=None, test_output_data=None):
    """Set the labels on a gerrit change using Gerrit and Gitiles REST API.

    Args:
      change_num (int): The number of the change to label.
      labels (dict): Mapping from label (Label) to value (int).
      gerrit_host (str): Base URL to curl against.
      credential_cookie_location (str): Path to git credential cookie.
      test_output_data (dict): Test output for set_change_labels.

    Returns:
      str: The applied labels (primarily for testing).
    """
    post_url = 'https://%s/changes/%s/revisions/1/review' % (gerrit_host,
                                                             change_num)
    post_json = {'labels': labels}

    credential_cookie_location = (
        credential_cookie_location or
        self.m.path.join(self.m.path['home'], '.git-credential-cache/cookie'))
    curl_params = [
        '-f', '-b', credential_cookie_location, '-X', 'POST', '-H',
        'Content-Type: application/json', '-d',
        self.m.json.dumps(post_json)
    ]
    test_output_data = test_output_data or self.m.json.dumps(post_json)

    post_json = {'labels': labels}
    data = self.m.easy.stdout_step('curl %s' % post_url,
                                   ['curl'] + curl_params + [post_url],
                                   ok_ret={0}, test_stdout=test_output_data)
    return data
