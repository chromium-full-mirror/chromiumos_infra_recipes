# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for CoP: A CL validator based on Google Cloud Build. go/cros-cop"""
import base64
import binascii
import json

from typing import Dict
from typing import List
from typing import Generator
from typing import Optional

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.cop import CopProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = {
    'buildbucket': 'recipe_engine/buildbucket',
    'depot_gerrit': 'depot_tools/gerrit',
    'easy': 'easy',
    'file': 'recipe_engine/file',
    'json': 'recipe_engine/json',
    'path': 'recipe_engine/path',
    'properties': 'recipe_engine/properties',
    'step': 'recipe_engine/step',
    'tricium': 'recipe_engine/tricium',
    'src_state': 'src_state',
    'gerrit': 'gerrit',
    'raw_io': 'recipe_engine/raw_io',
    'support': 'support',
    'test_util': 'test_util',
    'cros_infra_config': 'cros_infra_config',
}

PROPERTIES = CopProperties



def _run_script(api: RecipeApi, script: str, data_input: Dict,
                add_json_log: bool = True) -> Dict:
  """Run a helper script from the resource folder."""
  result = api.step(
      api.path.basename(script),
      [
          'vpython3',
          api.resource(script),
          '-input-json',
          api.json.input(data_input),
          '-output-json',
          api.json.output(add_json_log=add_json_log),
      ],
  )
  return result.json.output


def _gen_build_config(api: RecipeApi, user_yaml: str, substitutions: Dict,
                      files: List) -> Dict:
  """Combine the user build configuration with the base configuration."""
  data_in = {
      'base_yaml': api.resource('base.yaml'),
      'user_yaml': user_yaml,
      'substitutions': substitutions,
      'files': files,
  }
  return _run_script(api, 'generate_build_config.py', data_in)


def _launch_build(api: RecipeApi, project: str, build_config: Dict) -> str:
  """Launch a Google Cloud Build with the given configuration."""
  data_in = {
      'build_config': build_config,
      'project': project,
  }
  data_out = _run_script(api, 'launch_build.py', data_in)
  return data_out['id'], data_out['log_url']


def _wait_for_build_completion(api: RecipeApi, project: str,
                               build_id: str) -> None:
  """Wait for a Google Cloud Build to finish."""
  data_in = {
      'build_id': build_id,
      'project': project,
  }
  _run_script(api, 'monitor_build.py', data_in)


def _fetch_results(api: RecipeApi, project: str, build_id: str) -> Dict:
  """Fetch the logs from a completed Google Cloud Build."""
  data_in = {
      'build_id': build_id,
      'project': project,
  }
  return _run_script(api, 'fetch_results.py', data_in)


def _fetch_cop_file(api: RecipeApi, host: str, change_id: str,
                    patch_set: int) -> Optional[str]:
  """Download a user build configuration from gitiles."""

  url = 'https://%s/changes/%s/revisions/%d/files/%s/content' % (
      host, change_id, patch_set, '.cop%2Fbuild.yaml')
  data = api.easy.stdout_step('cop-fetch-file', ['curl', '-f', url])
  try:
    return base64.b64decode(data).decode('utf-8')
  except binascii.Error as e:
    raise api.step.StepFailure('CoP has invalid encoding.') from e


def _set_gerrit_review(api: RecipeApi, patch_set, body, name):
  """Call gerrit API to set review. Returns whether the step succeeded."""
  try:
    api.depot_gerrit.call_raw_api(
        'https://' + patch_set.host, '/changes/%s/revisions/%d/review/' %
        (patch_set.change_id, patch_set.patch_set), method='POST', body=body,
        accept_statuses=[200], name=name)
  except api.step.InfraFailure:
    return False
  return True


def _get_overall_comment(log: str, log_url: str, build_passed: bool,
                         log_url_set_in_review_comment: bool,
                         hide_full_logs: bool) -> Optional[str]:
  """Get the overall status comment. None if it should not be commented."""
  comment = f'CoP Log URL: {log_url}'
  if not hide_full_logs:
    comment += f'\n{_wrap_log(log)}'

  if not log_url_set_in_review_comment:
    # We failed to comment the log URL when sending the Verified vote to Gerrit.
    # The overall log should be commented for the log URL.
    return comment
  if build_passed:
    # Don't comment if the build passed.
    return None
  if hide_full_logs:
    # If hide_full_logs is set, the comment contains the log URL only,
    # which should already be sent along with the Verified vote.
    return None
  return comment


def _wrap_log(log: str) -> str:
  """Wrap log in a markdown code block and limit the size."""
  return f'```\n{log[-16000:]}\n```'


def RunSteps(api: RecipeApi, properties: CopProperties) -> None:

  with api.step.nest('validate properties') as presentation:
    if not properties.project_name:
      raise api.step.InfraFailure('No Google Cloud project name provided')

  with api.step.nest('validate inputs') as presentation:
    gerrit_changes = api.src_state.gerrit_changes
    if len(gerrit_changes) > 1:
      raise api.step.StepFailure('More than one change given.')
    if not gerrit_changes and not api.cros_infra_config.is_staging:
      presentation.step_text = 'No changes given: Build is POINTLESS.'
      return
    if len(gerrit_changes) == 1:
      presentation.step_text = 'One change from Tricium'
    else:
      presentation.step_text = 'Running from stagging builder with default CLs'

  with api.step.nest('get change') as presentation:
    if not gerrit_changes:
      # Based on 'validate inputs' logic, gerrit_changes should
      # only ever be empty during staging builds.
      # For staging builds with no gerrit_changes, assign a test change.
      assert api.cros_infra_config.is_staging
      change = GerritChange(change=4420967, project='infra/cop',
                            host='chromium-review.googlesource.com', patchset=1)
      presentation.properties['change_type'] = 'fixed_change'
    else:
      presentation.properties['change_type'] = 'tricium'
      change = gerrit_changes[0]

    patch_set = api.gerrit.fetch_patch_set_from_change(change,
                                                       include_commit_info=True,
                                                       include_files=True)
  with api.step.nest('check branch') as presentation:
    if patch_set.branch.startswith(('release-R', 'stabilize')):
      presentation.step_text = 'Branch not reviewed'
      return

  with api.step.nest('check committer') as presentation:
    committer = patch_set.commit_info['committer']['email']
    if not committer.endswith(('.google.com', '@chromium.org', '@google.com')):
      presentation.step_text = 'Committer must be related to Google'
      return

  with api.step.nest('check CoP') as presentation:
    try:
      user_yaml = _fetch_cop_file(api, patch_set.host, patch_set.change_id,
                                  patch_set.patch_set)
    except api.step.StepFailure:
      presentation.step_text = 'No cop file: Exiting'
      return

  with api.step.nest('generate build config') as presentation:
    subs = {
        '_REF': patch_set.git_fetch_ref,
        '_URL': patch_set.git_fetch_url,
    }
    build_config = _gen_build_config(api, user_yaml, subs,
                                     list(patch_set.file_infos))
    if not build_config:
      presentation.step_text = 'Empty build: Exiting'
      return

    cop_hide_full_logs = build_config.pop('CoP_hide_full_logs', False)

  with api.step.nest('launch build') as presentation:
    build_id, log_url = _launch_build(api, properties.project_name,
                                      build_config)
    presentation.links['build'] = log_url

  with api.step.nest('await build completion') as presentation:
    _wait_for_build_completion(api, properties.project_name, build_id)

  with api.step.nest('fetch results') as presentation:
    results = _fetch_results(api, properties.project_name, build_id)
    build_passed = results['result']['status'] == 'SUCCESS'

  log_url_set_in_review_comment = False
  with api.step.nest('send Vote to Gerrit') as presentation:
    body = {
        'message':
            f'CoP build {results["result"]["status"]}; Logs: {results["result"]["log_url"]}',
        # Tag as autogenerated so votes on old patch sets are hidden by default
        # by Gerrit's UI.
        # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#review-input
        'tag':
            'autogenerated:cop~result',
    }
    if build_passed:
      # Make a silent vote if the CoP run passed.
      body.update({
          'notify': 'NONE',
          'ignore_automatic_attention_set_rules': True,
      })
    vote = 1 if build_passed else -1
    if api.cros_infra_config.is_staging:
      presentation.step_text = 'Do not vote or comment with the staging builder.'
    elif _set_gerrit_review(api, patch_set, body={
        'labels': {
            'Verified': vote
        },
        **body
    }, name='comment and vote'):
      presentation.step_text = 'Commented and Voted V %d.' % vote
      log_url_set_in_review_comment = True
    elif _set_gerrit_review(api, patch_set, body=body, name='comment only'):
      # If we can't vote we comment only, but also let the user know,
      # so they can change Gerrit's permissions.
      # The important things are the comments, not the vote.
      presentation.step_text = 'Commented but unable to Vote V %d: Check repo permissions.' % vote
      log_url_set_in_review_comment = True
    else:
      presentation.step_text = 'Cannot comment or vote V %d.' % vote

  with api.step.nest('send Tricium comments') as presentation:
    comment = _get_overall_comment(results['result']['log'],
                                   results['result']['log_url'], build_passed,
                                   log_url_set_in_review_comment,
                                   cop_hide_full_logs)
    if comment is not None:
      api.tricium.add_comment(f"CoP Result: {results['result']['status']}",
                              comment, '/PATCHSET_LEVEL')
    for step in results['steps']:
      name = f"CoP Step {step['id']} ({step['name']}): {step['status']}"
      api.tricium.add_comment(name, _wrap_log(step['log']), '/PATCHSET_LEVEL')
    api.tricium.write_comments()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  def test_builder(**kwargs) -> TestData:
    """Generate a test build."""
    kwargs.setdefault('builder', 'infra-presubmit')
    kwargs.setdefault('cq', True)
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  def gen_patch_sets(committer: str = 'noreply@google.com',
                     branch: str = 'main') -> Dict[int, Dict]:
    message = 'UPSTREAM: kcam a new camera kernel platform\nProbably the best framework ever'
    return {
        1: {
            'subject': message.splitlines()[0],
            'branch': branch,
            'revision_info': {
                'commit': {
                    'message': message,
                    'committer': {
                        'email': committer,
                    }
                },
                '_number': 1,
                'ref': 'refs/changes/1/23456789/3',
                'files': {
                    'Makefile': {
                        'lines_inserted': 1,
                        'size': 42,
                        'size_delta': 3
                    },
                },
            },
        },
    }

  def tricium_has_comments(check, step_odict, comments: list):
    """Assert that tricium has posted `comments`."""
    build_properties = post_process.GetBuildProperties(step_odict)
    check('tricium' in build_properties)
    tricium = json.loads(build_properties['tricium'])
    check('comments' in tricium)
    check(tricium['comments'] == comments)

  yield api.test(
      'unset-properties', test_builder(revision=None, cq=False),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test('basic',
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

  yield api.test('unchecked-branch', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets(branch='release-R117-15572.B')),
                 api.post_check(post_process.StepSuccess, 'check branch'),
                 api.post_check(post_process.DoesNotRun, 'check committer'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))
  yield api.test('unknown-committer', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets(committer='joe@hotmail.com')),
                 api.post_check(post_process.StepSuccess, 'check committer'),
                 api.post_check(post_process.DoesNotRun, 'check CoP'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  yield api.test('missing-user-yaml', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file', stdout=api.raw_io.output('NotAbase64')),
                 api.post_check(post_process.StepSuccess, 'check committer'),
                 api.post_check(post_process.DoesNotRun, 'generate build config'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  cop_file = base64.b64encode('{"test_step:" 1}'.encode('ascii'))
  yield api.test('empty-run', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output([])),
                 api.post_check(post_process.StepSuccess, 'generate build config'),
                 api.post_check(post_process.DoesNotRun, 'launch build'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  config_file = {'steps': [1, 2, 3]}
  cloud_build = {'id': 'acabad0', 'log_url': 'http://google.com'}
  results = {
      'result': {
          'status': 'SUCCESS',
          'log': 'Soo good',
          'log_url': 'https://example.com/build/logs',
      },
      'steps': [{
          'id': '1',
          'name': 'run hello world',
          'status': 'SUCCESS',
          'log': 'Hello World'
      }]
  }
  yield api.test('success-run', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output(config_file)),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.step_data('send Vote to Gerrit.gerrit comment and vote',api.json.output(None)),
                 api.post_check(post_process.StepSuccess, 'send Vote to Gerrit'),
                 api.post_check(post_process.PropertyEquals, 'change_type', 'tricium'),
                 api.post_check(post_process.StepTextContains,'send Vote to Gerrit',('Commented and Voted',)),
                 api.post_check(tricium_has_comments,[{'category': 'CoP Step 1 (run hello world): SUCCESS', 'message': '```\nHello World\n```', 'path': '/PATCHSET_LEVEL'}]),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))
  yield api.test('success-run-cannot-vote', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output(config_file)),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.step_data('send Vote to Gerrit.gerrit comment and vote',retcode=1),
                 api.step_data('send Vote to Gerrit.gerrit comment only',api.json.output({})),
                 api.post_check(post_process.PropertyEquals,'change_type','tricium'),
                 api.post_check(post_process.StepTextContains,'send Vote to Gerrit',('Commented but unable to Vote',)),
                 api.post_check(tricium_has_comments,[{'category': 'CoP Step 1 (run hello world): SUCCESS', 'message': '```\nHello World\n```', 'path': '/PATCHSET_LEVEL'}]),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))
  yield api.test('success-run-cannot-vote-or-comment', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output(config_file)),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.step_data('send Vote to Gerrit.gerrit comment and vote',retcode=1),
                 api.step_data('send Vote to Gerrit.gerrit comment only',retcode=1),
                 api.post_check(post_process.PropertyEquals,'change_type','tricium'),
                 api.post_check(post_process.StepTextContains,'send Vote to Gerrit',('Cannot comment or vote',)),
                 api.post_check(tricium_has_comments,[{'category': 'CoP Result: SUCCESS', 'message': 'CoP Log URL: https://example.com/build/logs\n```\nSoo good\n```', 'path': '/PATCHSET_LEVEL'}, {'category': 'CoP Step 1 (run hello world): SUCCESS', 'message': '```\nHello World\n```', 'path': '/PATCHSET_LEVEL'}]),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  yield api.test('staging-run', test_builder(gerrit_changes=[]),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.buildbucket.generic_build(bucket='staging'),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output(config_file)),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.post_check(post_process.StepSuccess, 'send Tricium comments'),
                 api.post_check(post_process.StepTextContains,'send Vote to Gerrit',('Do not vote or comment',)),
                 api.post_check(post_process.DoesNotRun, 'send Vote to Gerrit.gerrit comment and vote','send Vote to Gerrit.gerrit comment only'),
                 api.post_check(post_process.PropertyEquals,'change_type','fixed_change'),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  results = {
      'result': {
          'status': 'FAILURE',
          'log': 'Soo good',
          'log_url': 'https://example.com/build/logs',
      },
      'steps': [{
          'id': '1',
          'name': 'run bye world',
          'status': 'FAILURE',
          'log': 'Hello World'
      }]
  }
  yield api.test('failure-run', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output(config_file)),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.post_check(post_process.StepSuccess, 'send Vote to Gerrit'),
                 api.post_check(post_process.PropertyEquals,'change_type','tricium'),
                 api.post_check(tricium_has_comments,[{'category': 'CoP Result: FAILURE', 'message': 'CoP Log URL: https://example.com/build/logs\n```\nSoo good\n```', 'path': '/PATCHSET_LEVEL'}, {'category': 'CoP Step 1 (run bye world): FAILURE', 'message': '```\nHello World\n```', 'path': '/PATCHSET_LEVEL'}]),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))

  yield api.test('failure-run-hide-full-logs', test_builder(gerrit_changes=change),
                 api.gerrit.set_gerrit_fetch_changes_response(
                    'get change', change, gen_patch_sets()),
                 api.step_data('check CoP.cop-fetch-file',stdout=api.raw_io.output(cop_file)),
                 api.step_data('generate build config.generate_build_config.py',api.json.output({'CoP_hide_full_logs': True, **config_file})),
                 api.step_data('launch build.launch_build.py',api.json.output(cloud_build)),
                 api.step_data('fetch results.fetch_results.py',api.json.output(results)),
                 api.post_check(post_process.StepSuccess, 'send Vote to Gerrit'),
                 api.post_check(post_process.PropertyEquals,'change_type','tricium'),
                 api.post_check(tricium_has_comments,[{'category': 'CoP Step 1 (run bye world): FAILURE', 'message': '```\nHello World\n```', 'path': '/PATCHSET_LEVEL'}]),
                 api.post_process(post_process.DropExpectation)) + \
                 api.properties(CopProperties(project_name='name'))
