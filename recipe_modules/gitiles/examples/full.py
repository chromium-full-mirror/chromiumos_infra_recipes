# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test example for using the Gitiles recipe module."""
import base64

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'gitiles',
]



def RunSteps(api):
  api.gitiles.fetch_revision('testgerrit', 'my/project', 'main')
  api.gitiles.fetch_revision('testgerrit', 'my/project', 'refs/heads/main')

  commit = GitilesCommit(host='host.example.com', project='project/name',
                         ref='refs/heads/main', id='snap')
  api.assertions.assertEqual(
      api.gitiles.repo_url(commit), 'https://host.example.com/project/name')

  api.assertions.assertEqual(
      api.gitiles.file_url(commit, 'path/to/file'),
      'https://host.example.com/project/name/+/snap/path/to/file')

  api.assertions.assertEqual(
      api.gitiles.get_file('testgerrit', 'my/project',
                           'chromite/api/somefile.txt',
                           ref='refs/heads/coolref', public=False,
                           test_output_data=base64.b64encode(b'{"abc":123}')),
      b'{"abc":123}')

  api.assertions.assertEqual(
      api.gitiles.get_commit_metadata('testgerrit', 'my/project',
                                      'refs/heads/main', public=False,
                                      test_data={'commit': 'deadbeef'}),
      {'commit': 'deadbeef'})

  api.assertions.assertIsNone(
      api.gitiles.get_file('testgerrit', 'my/project',
                           'chromite/api/somefile.txt',
                           ref='refs/heads/coolref', test_output_data=None))

  api.assertions.assertRaises(StepFailure, api.gitiles.get_file,
                              host='testgerrit', project='my/project',
                              path='chromite/api/somefile.txt',
                              ref='refs/heads/coolref',
                              test_output_data='not base64 yo')

def GenTests(api):
  yield api.test('basic')
