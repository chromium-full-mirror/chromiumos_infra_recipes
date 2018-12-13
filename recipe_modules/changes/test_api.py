# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

EXAMPLE_GERRIT_CHANGE = {
    'status': 'NEW',
    'created': '2017-01-30 13:11:20.000000000',
    '_number': 91827,
    'change_id': 'Ideadbeef',
    'project': 'chromium/src',
    'has_review_started': False,
    'branch': 'master',
    'subject': 'Change title',
    'revisions': {
        '184ebe53805e102605d11f6b143486d15c23a09c': {
            '_number': 1,
            'commit': {
                'message': 'Change commit message',
            },
            'fetch': {
                'http': {
                    'url': 'https://chromium.googlesource.com/chromium/src',
                    'ref': 'refs/changes/27/91827/1',
                }
            }
        },
    },
}


class ChangesTestApi(recipe_test_api.RecipeTestApi):

  def get_gerrit_change_data(self):
    return self.m.json.output([EXAMPLE_GERRIT_CHANGE])

  def buildbucket_gerrit_change(self, patch_set=1):
    return self.m.buildbucket.try_build(change_number=91827,
                                        patch_set=patch_set)
