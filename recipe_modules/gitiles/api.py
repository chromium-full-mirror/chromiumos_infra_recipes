# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for working with Gitiles."""

import base64
import binascii
from urllib import parse
from typing import Dict, Optional

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

_DEFAULT_CREDENTIAL_COOKIE_LOCATION = '.git-credential-cache/cookie'


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

  def get_commit_metadata(self, host: str, project: str, revision_or_ref: str,
                          public: bool = True,
                          credential_cookie_location: Optional[str] = None,
                          step_name: Optional[str] = None,
                          test_data: Optional[Dict] = None) -> Dict:
    """Returns commit metadata.

    Args:
      host: Gerrit host, e.g. chrome-internal.googlesource.com.
      project: Gerrit project, e.g. chromiumos/chromite.
      revision_or_ref: The revision or ref you are fetching, e.g. refs/heads/main.
      public: If False, will look in .git-credential-cache for an authorization
          cookie and use it in the curl. Default: True.
      credential_cookie_location: The credential cookie location.
          Default: '~/.git-credential-cache/cookie'.
      step_name: Name of the step.
      test_data: JSON response from gitiles.

    Returns:
      The JSON response from gitiles.
    """
    test_data = test_data or {}
    credential_cookie_location = (
        credential_cookie_location or self.m.path.join(
            self.m.path.home_dir, _DEFAULT_CREDENTIAL_COOKIE_LOCATION))
    cred_cache_cmd = [] if public else ['-b', credential_cookie_location]
    file_url_part = '/'.join((project, '+', revision_or_ref))
    if not public:
      file_url_part = 'a/' + file_url_part
    url = parse.urlunparse(
        ('https', host, file_url_part, '', 'format=JSON', ''))
    with self.m.step.nest(step_name or 'fetch commit metadata') as pres:
      data = self.m.step(
          'curl %s' % url, ['curl'] + cred_cache_cmd + [url], ok_ret={0},
          stdout=self.m.raw_io.output(),
          step_test_data=lambda: self.m.raw_io.test_api.stream_output(
              b")]}'\n" + self.m.json.dumps(test_data).encode())).stdout
      pres.logs['response'] = data
      return self.m.json.loads(data.removeprefix(b")]}'\n"))

  def get_file(self, host, project, path, ref=None, public=True,
               credential_cookie_location=None, step_name=None,
               test_output_data=None, retries=0):
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
      step_name: (str): Name of the step.
      test_output_data (str): Test output for curl.
      retries: (int): number of retires on transient errors.

    Returns:
      (str) The contents of the file as a string, None on 404, or raise
          StepFailure on unexpected curl return.
    """
    test_output_data = test_output_data or self._test_data.get('get_file')
    credential_cookie_location = (
        credential_cookie_location or self.m.path.join(
            self.m.path.home_dir, _DEFAULT_CREDENTIAL_COOKIE_LOCATION))
    cred_cache_cmd = [] if public else ['-b', credential_cookie_location]
    curl_retry_cmd = ['--retry', str(retries)] if retries else []
    ref = ref or 'HEAD'
    file_url_part = '/'.join((project, '+', ref, path))
    if not public:
      file_url_part = 'a/' + file_url_part
    url = parse.urlunparse(
        ('https', host, file_url_part, '', 'format=TEXT', ''))
    with self.m.step.nest(step_name or 'fetch gitiles file') as pres:
      data = self.m.step(
          'curl %s' % url,
          # TODO(b/385314410): Use --fail-with-body once all bots have newer curl.
          ['curl', '-f', '--write-out', 'HTTP_CODE=%{http_code}'] +
          cred_cache_cmd + curl_retry_cmd + [url],
          stdout=self.m.raw_io.output(),
          # curl returns retcode of 22 when requested resource is not fetched..
          # This return code is only returned with -f specified. Without -f it
          # returns retcode of 0 and output the body of the page itself.
          ok_ret={0, 22},
          step_test_data=lambda: self.m.raw_io.test_api.stream_output(
              b'HTTP_CODE=404' if test_output_data is None else
              (test_output_data.encode() if isinstance(test_output_data, str)
               else test_output_data) + b'HTTP_CODE=200', retcode=22
              if test_output_data is None else 0))
      curl_ret = data.retcode
      http_code = int(
          data.stdout[data.stdout.rindex(b'HTTP_CODE='):].lstrip(b'HTTP_CODE='))
      data = data.stdout[:data.stdout.rindex(b'HTTP_CODE=')]
      if curl_ret and http_code == 404:
        return None
      if curl_ret == 22:  # pragma: nocover
        # TODO(b/385314410): include error response data once all bots have
        # newer curl.
        raise StepFailure(f'curl failed with HTTP {http_code}.')
      try:
        decoded_data = base64.b64decode(data)
      except binascii.Error as e:
        pres.logs['raw data'] = data
        raise StepFailure('non base64 data returned from gitiles') from e
      pres.logs['data'] = decoded_data
      return decoded_data
