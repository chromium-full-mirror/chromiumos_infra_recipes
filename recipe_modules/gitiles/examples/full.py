# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'gitiles',
]

from recipe_engine.recipe_api import StepFailure

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit


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
                           ref='refs/heads/coolref'), '{"abc":123}')

  api.assertions.assertRaises(StepFailure, api.gitiles.get_file,
                              host='testgerrit', project='my/project',
                              path='chromite/api/somefile.txt',
                              ref='refs/heads/coolref',
                              test_output_data='not base64 yo')

  labels = {
      'labels': {
          'Code-Review': 2,
          'Verified': 1,
      }
  }
  api.assertions.assertEqual(
      api.gitiles.set_change_labels(commit.id, labels['labels'],
                                    'chromium-review.googlesource.com'),
      '{"labels": {"Code-Review": 2, "Verified": 1}}')

  labels = {
      'Not-A-Label': 2,
  }
  api.assertions.assertEqual(
      'label "Not-A-Label" is not a configured label',
      api.gitiles.set_change_labels(
          change_num=commit.id, labels=labels,
          gerrit_host='chromium-review.googlesource.com',
          test_output_data='label "Not-A-Label" is not a configured label'))


def GenTests(api):
  yield api.test('basic', api.gitiles.get_file('{"abc":123}'))
