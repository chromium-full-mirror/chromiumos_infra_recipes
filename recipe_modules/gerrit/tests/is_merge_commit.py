#  -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the is_merge_commit function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):

  api.assertions.assertEqual(
      api.gerrit.is_merge_commit(123, 'mygithost.google.com'),
      api.properties['expected_value'])


def GenTests(api):
  yield api.test(
      'not-merge-commit',
      api.gerrit.set_is_merge_commit(123, 'mygithost.google.com', False),
      api.properties(expected_value=False),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/changes/123/revisions/current/mergelist'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'merge-commit',
      api.gerrit.set_is_merge_commit(123, 'mygithost.google.com', True),
      api.properties(expected_value=True),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/changes/123/revisions/current/mergelist'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'passed-on-retry',
      api.gerrit.set_is_merge_commit(123, 'mygithost.google.com', True,
                                     iteration=2),
      api.properties(expected_value=True),
      api.step_data(
          'curl https://mygithost.google.com/changes/123/revisions/current/mergelist',
          retcode=1),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/changes/123/revisions/current/mergelist (2)'
      ),
      api.post_process(post_process.DropExpectation),
  )
