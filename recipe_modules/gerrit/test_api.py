# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from .api import PatchSet


class ChangesTestApi(recipe_test_api.RecipeTestApi):

  def test_response(self, request, gerrit_change, values_dict=None):
    project = gerrit_change.project if gerrit_change else ''
    values = dict(project=project or 'chromium/src')
    values.update(values_dict or {})
    change_number = request['change_number']
    resp = request.copy()
    resp['info'] = {
        '_number': change_number,
        'status': values.get('status', 'NEW'),
        'created': values.get('created', '2017-01-30 13:11:20.000000000'),
        'updated': values.get('updated', '2017-02-01 13:11:20.000000000'),
        'submitted': values.get('submitted', '2017-02-02 13:11:20.000000000'),
        'change_id': values.get('change_id', 'Ideadbeef'),
        'project': values.get('project', 'chromium/src'),
        'has_review_started': values.get('has_review_started', False),
        'branch': values.get('branch', self.m.src_state.default_branch),
        'subject': values.get('subject', 'Change title'),
        'hashtags': values.get('hashtags', []),
        'messages': values.get('messages', []),
    }
    ref = values.get(
        'ref', 'refs/changes/%s/%d/%d' % (
            ('%02d' % request['change_number'])[-2:],
            request['change_number'],
            request['patch_set'],
        ))
    resp['revision_info'] = values.get(
        'revision_info', {
            'commit': {
                'message':
                    values.get('message',
                               self.test_gerrit_change_description()),
            },
            'fetch': {
                'http': {
                    'url':
                        values.get(
                            'url', 'https://%s/%s' % (request['host'].replace(
                                '-review', ''), resp['info']['project'])),
                    'ref':
                        ref,
                }
            },
            'ref':
                ref,
            'files':
                values.get('files', {
                    'my/fake/file': {
                        'status': 'A',
                        'size_delta': 0,
                        'size': 0,
                    },
                })
        })
    return resp

  def set_gerrit_fetch_changes_response(self, step_name, changes,
                                        values_dict=None):
    """Set the response from gerrit-fetch-changes.

    Args:
      step_name (str): name of the step calling gerrit.fetch_patch_sets.
      changes (list[GerritChange]): The list of changes which will be found.
      values_dict (dict): Dictionary of {change_number: values} to provide field
          values to test_response.

    Returns:
      (StepTestData) test data instance for the test.
    """
    req = []
    resp = []
    for change in changes:
      request = dict(host=change.host, change_number=change.change,
                     patch_set=change.patchset)
      req.append(request)
      values = dict(project=change.project) if change.project else {}
      values.update(values_dict.get(change.change, {}))
      resp.append(self.test_response(request, change, values))

    resp = dict(changes=resp)
    prefix = '%s.' % step_name if step_name else ''
    return self.step_data(prefix + 'gerrit-fetch-changes',
                          stdout=self.m.json.output(resp))

  def test_gerrit_fetch_changes(self, input, gerrit_changes):
    return {
        'changes': map(self.test_response, input['changes'], gerrit_changes)
    }

  def test_patch_set(self):
    return PatchSet(
        self.test_response(
            {
                'host': 'chromium',
                'change_number': 12345,
                'patch_set': 1,
            }, None))

  def test_gerrit_change_url(self):
    return 'https://chromium-review.googlesource.com/c/chromiumos/chromite/+/1'

  def test_gerrit_change_description(self):
    return 'a quick description\n\nChange-Id: deadbeef\n'

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
