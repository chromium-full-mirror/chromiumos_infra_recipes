# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

gerrit_changes_json = [
    {
        '_number': 91827,
        'project': 'chromium/src',
    },
    {
        '_number': 91828,
        'project': 'chromium/src',
    },
]

values_dict = {
    91827:
        dict(
            status='NEW', created='2021-01-25 13:11:20.000000000',
            change_id='Ideadbeef', project='chromium/src',
            has_review_started=False, branch='main', subject='Overridden title',
            revisions={
                '184ebe53805e102605d11f6b143486d15c23a09c': {
                    '_number': '23981',
                    'commit': {
                        'message': 'Overridden change commit message',
                    }
                }
            }),
    91828:
        dict(
            status='MERGED',
            created='2021-02-25 13:11:20.000000000',
            submitted='2021-02-26 13:11:20.000000000',
            change_id='Ideadbeef02',
            project='chromium/src',
            has_review_started=True,
            branch='main',
            subject='Overridden title',
        )
}


def RunSteps(api):
  changes = api.gerrit.query_changes('https://chromium-review.googlesource.com',
                                     [('topic', 'pupr')])
  api.assertions.assertEqual(len(changes), 2)


def GenTests(api):
  yield api.test(
      'basic',
      api.gerrit.set_query_changes_response(
          '', gerrit_changes_json, 'https://chromium-review.googlesource.com',
          values_dict))
