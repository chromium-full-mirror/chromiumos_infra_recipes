#  -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'expected': Property(help='Whether the change is mergeable'),
    'remote': Property(help='The remote repository location')
}


def RunSteps(api, remote, expected):
  change_id = '1'
  result = api.gerrit.get_change_mergeable(change_id, remote)
  api.assertions.assertEqual(expected, result)


def GenTests(api):
  yield api.test(
      'mergeable',
      api.properties(remote='mygithost.google.com/somerepo', expected=True),
      api.gerrit.set_get_change_mergeable('', 'mygithost.google.com/somerepo',
                                          1, 'current', True),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/somerepo/changes/1/revisions/current/mergeable'
      ))
  yield api.test(
      'not-mergeable',
      api.properties(remote='mygithost.google.com/somerepo', expected=False),
      api.gerrit.set_get_change_mergeable('', 'mygithost.google.com/somerepo',
                                          1, 'current', False),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/somerepo/changes/1/revisions/current/mergeable'
      ))
  yield api.test(
      'no-mergeable-in-response',
      api.properties(remote='mygithost.google.com/somerepo', expected=None),
      api.gerrit.set_get_change_mergeable('', 'mygithost.google.com/somerepo',
                                          1, 'current', None),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/somerepo/changes/1/revisions/current/mergeable'
      ), api.post_check(post_process.StatusAnyFailure),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'malformed-mergeable',
      api.properties(remote='mygithost.google.com/somerepo', expected=None),
      api.gerrit.set_get_change_mergeable('', 'mygithost.google.com/somerepo',
                                          1, 'current', 'FooBar'),
      api.post_process(
          post_process.MustRun,
          'curl https://mygithost.google.com/somerepo/changes/1/revisions/current/mergeable'
      ), api.post_check(post_process.StatusAnyFailure),
      api.post_process(post_process.DropExpectation))
