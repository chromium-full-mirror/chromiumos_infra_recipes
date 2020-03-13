# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
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
        'updated': '2017-02-01 13:11:20.000000000',
        'submitted': '2017-02-02 13:11:20.000000000',
        'change_id': 'Ideadbeef',
        'project': 'chromium/src',
        'has_review_started': False,
        'branch': 'master',
        'subject': 'Change title',
    }
    ref = 'refs/changes/%s/%d/%d' % (
        str(request['change_number'])[-2:],
        request['change_number'],
        request['patch_set'],
    )
    resp['revision_info'] = {
        'commit': {
            'message': 'Change commit message',
        },
        'fetch': {
            'http': {
                'url': ('https://%s/chromium/src' % request['host']).replace(
                    '-review', ''),
                'ref':
                    ref,
            }
        },
        'ref': ref,
        'files': {
            'my/fake/file': {
                'status': 'A',
                'size_delta': 0,
                'size': 0,
            },
        },
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

  def test_gerrit_change_url(self):
    return 'https://chromium-review.googlesource.com/c/chromiumos/chromite/+/1'

  def test_gerrit_change_description(self):
    return '''\
a quick description

Change-Id: deadbeef
    '''

  def test_changes_are_submittable(self, errors=[]):
    """Test output for changes_are_submitted.

    Args:
      errors (list(str)): errors that the support binary reports.
    """
    return {'errors': errors}

  def simulated_changes_are_submittable(self, submittable=True):
    """Simulates the step_data for invoking git-test-submit binary.

    Args:
      submittable (bool): whether the binary should return that the CLs can be
          cherry-picked.

    Returns:
      bool
    """
    output = {'errors': []}
    if not submittable:
      output['errors'].append('some cherry pick error line 1\nline2')
    return self.step_data('check for merge conflicts.git-test-submit',
                          stdout=self.m.json.output(output))

  def simulated_create_change(self, step_name, gerrit_change_url):
    """Simulates creation of a Gerrit change.

    Args:
      step_name (str): Step name to set step_data for.
      gerrit_change_url (GerritChange): Fake upload URL for the change..

    Returns:
      StepData: Resulting step data.
    """
    return self.m.git_cl.output(step_name + '.git_cl status', gerrit_change_url)
