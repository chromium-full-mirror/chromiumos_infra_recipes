# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for CoP: A CL validator based on Google Cloud Build. go/cros-cop"""

from typing import Dict, Generator, Optional

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.cop import CopProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import (RecipeTestApi, TestData)

DEPS = [
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/tricium',
    'src_state',
    'gerrit',
    'support',
    'test_util',
]

PROPERTIES = CopProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def _run_script(api: RecipeApi, script: str, data_input: Dict) -> Dict:
  """Run a helper script from the resource folder."""
  result = api.step(
      api.path.basename(script),
      [
          'vpython3',
          api.resource(script),
          '-input-json',
          api.json.input(data_input),
          '-output-json',
          api.json.output(),
      ],
  )
  return result.json.output


def _gen_build_config(api: RecipeApi, user_yaml: str,
                      substitutions: Dict) -> Dict:
  """Combine the user build configuration with the base configuration."""
  data_in = {
      'base_yaml': api.resource('base.yaml'),
      'user_yaml': user_yaml,
      'substitutions': substitutions,
  }
  return _run_script(api, "generate_build_config.py", data_in)


def _launch_build(api: RecipeApi, project: str, token: str,
                  build_config: Dict) -> str:
  """Launch a Google Cloud Build with the given configuration."""
  data_in = {
      'build_config': build_config,
      'project': project,
      'token': token,
  }
  return _run_script(api, "launch_build.py", data_in)['id']


def _wait_for_build_completion(api: RecipeApi, project: str, token: str,
                               build_id: str) -> None:
  """Wait for a Google Cloud Build to finish."""
  data_in = {
      'build_id': build_id,
      'project': project,
      'token': token,
  }
  _run_script(api, "monitor_build.py", data_in)


def _fetch_results(api: RecipeApi, project: str, token: str,
                   build_id: str) -> Dict:
  """Fetch the logs from a completed Google Cloud Build."""
  data_in = {
      'build_id': build_id,
      'project': project,
      'token': token,
  }
  return _run_script(api, "fetch_results.py", data_in)


def _fetch_cop_file(api: RecipeApi, host: str, project: str,
                    ref: str) -> Optional[str]:
  """Download a user build configuration from gitiles."""
  gitiles_input = {
      'file': {
          'host': host,
          'project': project,
          'ref': ref,
          'path': '.cop/build.yaml',
      }
  }

  try:
    gitiles_output = api.m.support.call('gitiles-fetch-file', gitiles_input)
  # File not present is returned as InfraFailure
  except api.step.InfraFailure:
    return None
  return gitiles_output['file']['content']


def RunSteps(api: RecipeApi, properties: CopProperties) -> None:

  with api.step.nest('validate properties') as presentation:
    if not properties.project_name:
      raise api.step.InfraFailure('No Google Cloud project name provided')

  with api.step.nest('validate inputs') as presentation:
    gerrit_changes = api.src_state.gerrit_changes
    # If there are no gerrit_changes, we're done.
    if len(gerrit_changes) == 0:
      presentation.step_text = 'No changes given: Build is POINTLESS.'
      return
    # If there is more than one gerrit_change, this recipe was invoked
    # incorrectly.
    if len(gerrit_changes) != 1:
      raise api.step.StepFailure('More than one change given.')

  with api.step.nest('check committer') as presentation:
    patch_set = api.m.gerrit.fetch_patch_set_from_change(
        gerrit_changes[0], include_commit_info=True)
    committer = patch_set.commit_info['committer']['email']
    if not committer.endswith(('.google.com', '@chromium.org', '@google.com')):
      presentation.step_text = 'Committer must be related to Google'
      return

  with api.step.nest('check CoP') as presentation:
    user_yaml = _fetch_cop_file(api, patch_set.short_host, patch_set.project,
                                patch_set.current_revision)
    if not user_yaml:
      presentation.step_text = 'No cop file: Exiting'
      return

  with api.step.nest('obtain Oauth2 token') as presentation:
    token = api.m.support.call('oauth2-get-token', None, add_json_log=True)
    auth_token = token['token']['access_token']

  with api.step.nest('generate build config') as presentation:
    subs = {
        '_REF': patch_set.current_revision,
        '_URL': patch_set.git_fetch_url,
        '_HOSTNAME': patch_set.host,
        '_TOKEN': auth_token
    }
    build_config = _gen_build_config(api, user_yaml, subs)

  with api.step.nest('launch build') as presentation:
    build_id = _launch_build(api, properties.project_name, auth_token,
                             build_config)

  with api.step.nest('wait build competion') as presentation:
    _wait_for_build_completion(api, properties.project_name, auth_token,
                               build_id)

  with api.step.nest('fetch results') as presentation:
    results = _fetch_results(api, properties.project_name, auth_token, build_id)

  with api.step.nest('send Tricium comments') as presentation:
    api.tricium.add_comment(f"CoP Result: {results['result']['status']}",
                            results['result']['log'], '/COMMIT_MSG')
    for step in results['steps']:
      name = f"CoP Step {step['id']} ({step['name']}): {step['status']}"
      api.tricium.add_comment(name, step['log'], '/COMMIT_MSG')
    api.tricium.write_comments()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def test_builder(**kwargs) -> TestData:
    """Generate a test build."""
    kwargs.setdefault('builder', 'infra-presubmit')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  def gen_patch_sets(committer: str = 'noreply@google.com') -> Dict[int, Dict]:
    message = 'UPSTREAM: kcam a new camera kernel platform\nProbably the best framework ever'
    return {
        1: {
            'subject': message.splitlines()[0],
            'branch': 'chromeos-2.4',
            'revision_info': {
                'commit': {
                    'message': message,
                    'committer': {
                        'email': committer,
                    }
                },
                '_number': 1,
            },
        },
    }

  yield api.test(
      'unset-properties', test_builder(revision=None, cq=False),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test('basic', api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  yield api.test('no-changes-given', test_builder(revision=None, cq=False),
                 api.post_check(post_process.StepSuccess, 'validate properties'),
                 api.post_check(post_process.DoesNotRun, 'check committer'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  two_changes = [
      GerritChange(change=1, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=1),
      GerritChange(change=2, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=2),
  ]
  yield api.test('too-many-changes', test_builder(gerrit_changes=two_changes),
                 api.post_check(post_process.StepSuccess, 'validate properties'),
                 api.post_check(post_process.StepFailure, 'validate inputs'),
                 api.post_process(post_process.DropExpectation),
                 status = 'FAILURE') + \
                 api.properties(CopProperties(project_name='name'))

  change = [
      GerritChange(change=1, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=1),
  ]

  yield api.test('unknown-committer', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'check committer', change, gen_patch_sets(committer='joe@hotmail.com')),
                 api.post_check(post_process.StepSuccess, 'check committer'),
                 api.post_check(post_process.DoesNotRun, 'check CoP'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  gitiles_file = {'file': {'content': 'Testing123',}}

  yield api.test('missing-user-yaml', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'check committer', change, gen_patch_sets()),
                 api.step_data('check CoP.gitiles-fetch-file',api.json.output(gitiles_file), retcode=1),
                 api.post_check(post_process.StepSuccess, 'check committer'),
                 api.post_check(post_process.DoesNotRun, 'obtain Oauth2 token'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  token = {'token': {'access_token': "fabada"}}
  cloud_build = {'id': 'acabad0'}
  results = {
      'result': {
          'status': 'SUCCESS',
          'log': 'Soo good',
      },
      'steps': [{
          'id': '1',
          'name': 'run hello world',
          'status': 'SUCCESS',
          'log': 'Hello World'
      }]
  }
  yield api.test('full-run', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'check committer', change, gen_patch_sets()),
                 api.step_data('check CoP.gitiles-fetch-file',stdout=api.json.output(gitiles_file)),
                 api.step_data('obtain Oauth2 token.oauth2-get-token',stdout=api.json.output(token)),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.post_check(post_process.StepSuccess, 'send Tricium comments'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))
