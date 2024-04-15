# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for working with Gitiles."""

import base64
import binascii
from urllib import parse

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
        self.m.path.join(self.m.path.home_dir, '.git-credential-cache/cookie'))
    cred_cache_cmd = [] if public else ['-b', credential_cookie_location]
    ref = ref or 'HEAD'
    file_url_part = '/'.join((project, '+', ref, path))
    url = parse.urlunparse(
        ('https', host, file_url_part, '', 'format=TEXT', ''))
    with self.m.step.nest('fetch gitiles file') as pres:
      data = self.m.easy.stdout_step('curl %s' % url,
                                     ['curl'] + cred_cache_cmd + [url],
                                     ok_ret={0}, test_stdout=test_output_data)
      try:
        decoded_data = base64.b64decode(data)
      except binascii.Error as e:
        pres.logs['raw data'] = data
        raise StepFailure('non base64 data returned from gitiles') from e
      pres.logs['data'] = decoded_data
      return decoded_data
