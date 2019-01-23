# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from .api import PatchSet


class ChangesTestApi(recipe_test_api.RecipeTestApi):

  def test_response(self, request):
    resp = request.copy()
    resp['info'] = {
        '_number': request['change_number'],
        'status': 'NEW',
        'created': '2017-01-30 13:11:20.000000000',
        'change_id': 'Ideadbeef',
        'project': 'chromium/src',
        'has_review_started': False,
        'branch': 'master',
        'subject': 'Change title',
    }
    resp['revision_info'] = {
        'commit': {
            'message': 'Change commit message',
        },
        'fetch': {
            'http': {
                'url': ('https://%s/chromium/src' % request['host']).replace(
                    '-review', ''),
                'ref':
                    'refs/changes/%s/%d/%d' % (
                        str(request['change_number'])[-2:],
                        request['change_number'],
                        request['patch_set'],
                    ),
            }
        }
    }
    return resp

  def test_gerrit_fetch_changes(self, input):
    return {'changes': map(self.test_response, input['changes'])}

  def test_patch_set(self):
    return PatchSet(
        self.test_response({
            'host': 'chromium',
            'change_number': 12345,
            'patch_set': 1,
        }))
