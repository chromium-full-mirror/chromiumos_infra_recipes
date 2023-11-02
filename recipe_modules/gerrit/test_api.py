# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to help with test cases that rely on the gerrit module."""

import itertools
import json
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
    values = {'project': project or 'chromium/src'}
    if values_dict is not None:
      values.update(values_dict)
    change_number = request['change_number']
    resp = request.copy()
    resp['info'] = {
        '_number': change_number,
        'status': values.get('status', 'NEW'),
        'created': values.get('created', '2017-01-30 13:11:20.000000000'),
        'updated': values.get('updated', '2017-02-01 13:11:20.000000000'),
        'submitted': values.get('submitted', '2017-02-02 13:11:20.000000000'),
        'submittable': values.get('submittable', False),
        'unresolved_comment_count': values.get('unresolved_comment_count', 0),
        'change_id': values.get('change_id', 'Ideadbeef'),
        'project': values.get('project', 'chromium/src'),
        'has_review_started': values.get('has_review_started', False),
        'branch': values.get('branch', self.m.src_state.default_branch),
        'subject': values.get('subject', 'Change title'),
        'topic': values.get('topic', 'Change topic'),
        'hashtags': values.get('hashtags', []),
        'labels': values.get('labels'),
        'messages': values.get('messages', []),
        'current_revision': values.get('current_revision', 'f000' * 10),
        'work_in_progress': values.get('work_in_progress', False)
    }
    if resp['info']['status'] == 'NEW':
      resp['info']['submitted'] = ''
    elif resp['info']['status'] == 'ABANDONED':
      resp['info']['submittable'] = False
      resp['info']['submitted'] = ''
    elif resp['info']['status'] == 'MERGED':
      resp['info']['submittable'] = False
      resp['info']['work_in_progress'] = False
    if 'patch_set' in values:
      resp['info']['patch_set'] = values['patch_set']
    ref = values.get(
        'ref', 'refs/changes/%s/%d/%d' % (
            ('%02d' % request['change_number'])[-2:],
            request['change_number'],
            request['patch_set'],
        ))
    resp['patch_set_revision'] = values.get('patch_set_revision', 'f000' * 10)
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

  def set_gerrit_fetch_changes_response(
      self, parent_step_name: str, changes: List[GerritChange],
      values_dict: Dict[int, JSONObject], iteration: int = 1,
      step_name: Optional[str] = None) -> recipe_test_api.TestData:
    """Return a TestData that sets the response from gerrit-fetch-changes.

    Args:
      parent_step_name: The name of the step calling gerrit.fetch_patch_sets.
      changes: The list of changes which will be found.
      values_dict: Dictionary of {change_number: values} to provide field values
          to _test_fetch_changes_response for each requested change.
      iteration: Which call this applies to for this step/endpoint.
      step_name: The name of current step.
    """
    iteration_str = '' if iteration == 1 else f' ({iteration})'
    resp_list = []
    for change in changes:
      request = {
          'host': change.host,
          'change_number': change.change,
          'patch_set': change.patchset,
      }
      values = {'project': change.project} if change.project else {}
      values.update(values_dict.get(change.change, {}))
      resp_list.append(
          self._test_fetch_changes_response(request, change, values))

    resp_dict = {'changes': resp_list}
    prefix = f'{parent_step_name}.' if parent_step_name else ''
    name = step_name or 'gerrit-fetch-changes'
    step_name = f'{prefix}{name}{iteration_str}'
    return self.step_data(step_name, stdout=self.m.json.output(resp_dict))

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

  def set_get_account_id(self, gerrit_host: str, email: str, value: int,
                         parent_step_name: Optional[str] = None,
                         iteration: int = 1) -> recipe_test_api.StepTestData:
    """Set the response from the Gerrit's Get Account API.

    Args:
      email: The email of the account to retrieve.
      gerrit_host: URL for the Gerrit host.
      value: The test response. If None, the "_account_id" field in the JSON
      response is omitted.
      parent_step_name: The parent step calling gerrit.get_account_id.
      iteration: Which call this applies to for this step/endpoint.

    Returns:
      Test data instance for the tests.
    """
    iteration = '' if iteration == 1 else f' ({iteration})'
    prefix = f'{parent_step_name}.' if parent_step_name else ''
    url = f'https://{gerrit_host}/accounts/{email}'
    step_name = f'{prefix}curl {url}{iteration}'
    values = {}
    if value is not None:
      values['_account_id'] = value
    return self.override_step_data(
        step_name,
        stdout=self.m.raw_io.output(")]}'\n" + self.m.json.dumps(values)))

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
    values = {}
    if value is not None:
      values['mergeable'] = value
    return self.override_step_data(
        step_name,
        stdout=self.m.raw_io.output(")]}'\n" + self.m.json.dumps(values)))

  def set_is_merge_commit(
      self, change_num: int, gerrit_host: str, test_value: bool,
      revision: Optional[str] = 'current', parent_step_name: Optional[str] = '',
      iteration: Optional[int] = 1) -> recipe_test_api.StepTestData:
    """Set the test response for gerrit.is_merge_commit.

    This is done by mocking the response from Gerrit's Get Merge List API.

    Args:
      change_num: The number of the change to check.
      gerrit_host: URL for the Gerrit host.
      test_value: Test response.
      revision: The revision of the change to check.
      parent_step_name: Name of the step calling gerrit.is_merge_commit.
      iteration: Which call this applies to for this step/endpoint.

    Returns:
      Test data instance for the tests.
    """
    url = f'https://{gerrit_host}/changes/{change_num}/revisions/{revision}/mergelist'
    iteration = '' if iteration == 1 else f' ({iteration})'
    prefix = f'{parent_step_name}.' if parent_step_name else ''
    step_name = f'{prefix}curl {url}{iteration}'

    resp = [{'commit': 1234}] if test_value else []
    return self.override_step_data(
        step_name,
        stdout=self.m.raw_io.output(")]}'\n" + self.m.json.dumps(resp)))

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

  def simulated_changes_are_submittable(
      self, submittable: bool = True, step_name_prefix: str = '',
      iteration: int = 1) -> recipe_test_api.TestData:
    """Return a TestData that sets the response for git-test-submit.

    Args:
      submittable: Whether the binary should return that the CLs can be
          cherry-picked.
      step_name_prefix: Optional prefix to step name for testing nested calls.
      iteration: Which call this applies to for this step/endpoint.
    """
    iteration_str = '' if iteration == 1 else f' ({iteration})'
    prefix = f'{step_name_prefix}.' if step_name_prefix else ''
    output: JSONObject = {'errors': []}
    if not submittable:
      output['errors'].append('some cherry pick error line 1\nline2')
    step_name = f'{prefix}check for merge conflicts{iteration_str}.git-test-submit'
    return self.step_data(step_name, stdout=self.m.json.output(output))

  def simulated_create_change(self, step_name: str, gerrit_change_url: str
                             ) -> recipe_test_api.TestData:
    """Return a TestData that sets the response for create_change().

    Args:
      step_name: Step name to set step_data for.
      gerrit_change_url: Fake upload URL for the change.
    """
    return self.m.git_cl.output(step_name + '.git_cl status', gerrit_change_url)

  def set_gerrit_related_changes(
      self,
      related_changes: Dict[str, List[Dict[str, str]]],
      step_name: str = '',
      iteration: int = 1,
      retcode: int = 0,
  ) -> recipe_test_api.StepTestData:
    """Sets the depot_tools API's get_changes() response.

    Args:
      step_name: name of the step calling gerrit.get_related_changes.
      related_changes: mock related changes.
      iteration: Which call this applies to for this step/endpoint.
      retcode: Retcode that should be used for the test code.
    """
    iteration_str = '' if iteration == 1 else f' ({iteration})'
    prefix = f'{step_name}.' if step_name else ''
    step_name = f'{prefix}call gerrit_related_changes{iteration_str}.read output json'

    return self.override_step_data(
        step_name, self.m.file.read_text(json.dumps(related_changes)),
        retcode=retcode)
