# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to help with test cases that rely on the gerrit module."""

import itertools
from typing import Dict, Iterable, List, Optional, Union

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from RECIPE_MODULES.chromeos.gerrit.api import ChangeInfo
from RECIPE_MODULES.chromeos.gerrit.api import JSONObject
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet


class ChangesTestApi(recipe_test_api.RecipeTestApi):

  def _test_fetch_changes_response(self, request: JSONObject,
                                   gerrit_change: GerritChange,
                                   values_dict: Optional[JSONObject] = None
                                  ) -> JSONObject:
    """Create and return a sample response for gerrit-fetch-changes.

    Args:
      request: A single change request that would be passed into the
        gerrit-fetch-changes tool.
      gerrit_change: The Gerrit change corresponding to that request, as would
        be passed into fetch_patch_sets().
      values_dict: Dict containing values for gerrit-fetch-changes to return.
        If not passed in, or if any fields are empty, defaults will be set.
    """
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
        'current_revision': values.get('current_revision', 'f000' * 10),
    }
    if 'patch_set' in values:
      resp['info']['patch_set'] = values['patch_set']
    ref = values.get(
        'ref', 'refs/changes/%s/%d/%d' % (
            ('%02d' % request['change_number'])[-2:],
            request['change_number'],
            request['patch_set'],
        ))
    resp['revision_info'] = values.get(
        'revision_info', {
            '_number':
                int(request.get('patch_set', 0)),
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

  def set_gerrit_fetch_changes_response(self, step_name: str,
                                        changes: List[GerritChange],
                                        values_dict: Dict[int, JSONObject],
                                        iteration: int = 1
                                       ) -> recipe_test_api.TestData:
    """Return a TestData that sets the response from gerrit-fetch-changes.

    Args:
      step_name: name of the step calling gerrit.fetch_patch_sets.
      changes: The list of changes which will be found.
      values_dict: Dictionary of {change_number: values} to provide field values
          to _test_fetch_changes_response for each requested change.
      iteration: Which call this applies to for this step/endpoint.
    """
    iteration_str = '' if iteration == 1 else f' ({iteration})'
    respList = []
    for change in changes:
      request = dict(host=change.host, change_number=change.change,
                     patch_set=change.patchset)
      values = dict(project=change.project) if change.project else {}
      values.update(values_dict.get(change.change, {}))
      respList.append(
          self._test_fetch_changes_response(request, change, values))

    respDict = dict(changes=respList)
    prefix = f'{step_name}.' if step_name else ''
    step_name = f'{prefix}gerrit-fetch-changes{iteration_str}'
    return self.step_data(step_name, stdout=self.m.json.output(respDict))

  def set_query_changes_response(self, step_name: str,
                                 changes: List[ChangeInfo], host_url: str,
                                 iteration: int = 1
                                ) -> recipe_test_api.StepTestData:
    """Return a TestData that sets the depot_tools API's get_changes() response.

    Args:
      step_name: name of the step calling gerrit.query_changes.
      change_infos: The list of changes which will be found.
      host_url: URL for the Gerrit host.
      iteration: Which call this applies to for this step/endpoint.
    """
    iteration_str = '' if iteration == 1 else f' ({iteration})'
    prefix = f'{step_name}.' if step_name else ''
    step_name = f'{prefix}query {host_url}{iteration_str}.gerrit changes'
    return self.override_step_data(step_name, self.m.json.output(changes))

  def set_get_change_mergeable(self, step_name: str, gerrit_host: str,
                               change_num: int, revision: str,
                               value: Union[bool, None, str], iteration: int = 1
                              ) -> recipe_test_api.StepTestData:
    """Set the response from the Gerrit's Get Mergeable API.

    Args:
      step_name: Name of the step calling gerrit.get_change_mergeable.
      gerrit_host: URL for the Gerrit host.
      change_num: The number of the change to check.
      revision: The revision of the change to check.
      value: The response. None and str values are only for the module unit
          test to emulate a malformed response from the API endpoint.
          If None, the "mergeable" field in the JSON response is omitted.
      iteration: Which call this applies to for this step/endpoint.

    Returns:
      Test data instance for the tests.
    """
    iteration = '' if iteration == 1 else ' (%d)' % iteration
    prefix = '%s.' % step_name if step_name else ''
    url = 'https://%s/changes/%s/revisions/%s/mergeable' % (
        gerrit_host, change_num, revision)
    step_name = '%scurl %s%s' % (prefix, url, iteration)
    if value is None:
      values = dict()
    else:
      values = dict(mergeable=value)
    return self.override_step_data(
        step_name,
        stdout=self.m.raw_io.output(')]}\'\n' + self.m.json.dumps(values)))

  def test_gerrit_fetch_changes(self, request: JSONObject,
                                gerrit_changes: List[GerritChange]
                               ) -> JSONObject:
    """Return a sample value request for _gerrit_fetch_changes().

    Args:
      request: The request object that would be passed into
        _gerrit_fetch_changes().
      gerrit_changes: The Gerrit changes that would be passed into
        _gerrit_fetch_changes().
    """
    return {
        'changes':
            list(
                map(lambda a: self._test_fetch_changes_response(*a),
                    itertools.zip_longest(request['changes'], gerrit_changes)))
    }

  def test_patch_set(self) -> PatchSet:
    """Return a sample patch set."""
    return PatchSet(
        self._test_fetch_changes_response(
            {
                'host': 'chromium',
                'change_number': 12345,
                'patch_set': 1,
            }, None))

  def test_gerrit_change_url(self) -> str:
    """Return a sample URL for a Gerrit change."""
    return 'https://chromium-review.googlesource.com/c/chromiumos/chromite/+/1'

  def test_gerrit_change_description(self) -> str:
    """Return a sample description (commit message) for a Gerrit change."""
    return 'a quick description\n\nChange-Id: deadbeef\n'

  def test_changes_are_submittable(self,
                                   errors: Iterable[str] = ()) -> JSONObject:
    """Return a sample output for the git-test-submit support tool.

    Args:
      errors: Errors that the support binary should report.
    """
    return {'errors': list(errors)}

  def simulated_changes_are_submittable(self, submittable: bool = True
                                       ) -> recipe_test_api.TestData:
    """Return a TestData that sets the response for git-test-submit.

    Args:
      submittable: Whether the binary should return that the CLs can be
          cherry-picked.
    """
    output: JSONObject = {'errors': []}
    if not submittable:
      output['errors'].append('some cherry pick error line 1\nline2')
    return self.step_data('check for merge conflicts.git-test-submit',
                          stdout=self.m.json.output(output))

  def simulated_create_change(self, step_name: str, gerrit_change_url: str
                             ) -> recipe_test_api.TestData:
    """Return a TestData that sets the response for create_change().

    Args:
      step_name: Step name to set step_data for.
      gerrit_change_url: Fake upload URL for the change.
    """
    return self.m.git_cl.output(step_name + '.git_cl status', gerrit_change_url)
