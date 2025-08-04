# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Success workflow tests for the signing recipe module."""

import functools
from typing import Any
from typing import Callable
from typing import Dict
from typing import List

from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'signing',
]


_RUNNING = {
    'status': {
        'status': 'running'
    },
}
_PASSED = {
    'status': {
        'status': 'passed'
    },
}
_FAILED = {
    'status': {
        'status': 'failed',
        'details': 'failed for reason foo'
    },
}
_FAILED_ALREADY_EXISTS = {
    'status': {
        'status': 'failed',
        'details': '...in SignArtifacts\n    raise ImageAlreadyExistsError...'
    },
}

_PASSED_COMPLETE = {
    'release_directory': 'directory1/directory2/releases',
    'status': {
        'status': 'passed'
    },
}
_FAILED_COMPLETE = {
    'release_directory': 'directory1/directory2/releases',
    **_FAILED
}
_FAILED_ALREADY_EXISTS_COMPLETE = {
    'release_directory': 'directory1/directory2/releases',
    **_FAILED_ALREADY_EXISTS
}


def _flatten_dict(d):
  """Flatten a dictionary.

  Specifically, this means converting an input like this:

  {'a': 1, 'b': {'c': 2, 'd': {'e': 3, 'f': 4}}}

  To this:

  {'a': 1, 'b.c': 2, 'b.d.e': 3, 'b.d.f': 4}

  An exception will be thrown if there's a collision in the keys.
  """

  result = {}
  for key, value in d.items():
    if isinstance(value, dict):
      for k, v in _flatten_dict(value).items():
        new_key = f'{key}.{k}'
        assert new_key not in result
        result[new_key] = v
    elif isinstance(value, (str, int)):
      result[key] = str(value)
    else:
      raise api.step.InfraFailure(  # pragma: no cover
          f'unexpected type: {value!r}')
  return result


def RunSteps(api: RecipeApi):
  metadata = api.signing.wait_for_signing([
      'gs://bucket/directory1/directory2/releases/file1.instructions',
      'gs://bucket/directory1/directory2/releases/file2.instructions',
  ])
  with api.step.nest('verify results') as child_step:
    signed_builds = api.signing.get_signed_build_metadata(metadata)

    for i, build in enumerate(signed_builds):
      pres = api.step.empty(str(i)).presentation
      if build:
        pres.tags.update(_flatten_dict(build))

    api.signing.verify_signing_success(metadata, child_step)


def GenTests(api: RecipeTestApi):

  def check_metadata(step: str, expected: List[Dict[str, Any]]):
    """Check that the step's meta_list equals given value.

    Assumes order does not matter.

    Args:
      step (str) - The step to check the meta_list of.
      expected (array) - The expected value of the meta_list.

    Usage:
      yield TEST + check_metadata('step-name', 'expected-text')
    """

    result = api.post_check(post_process.MustRun, step)

    for i, elem in enumerate(expected):
      step_i = f'{step}.{i}'
      result += api.post_check(post_process.MustRun, step_i)

      if expected[i] is None:
        result += api.post_check(post_process.NumTagsEquals, step_i, 0)
        continue

      expected_tags = _flatten_dict(expected[i])
      result += api.post_check(post_process.NumTagsEquals, step_i,
                               len(expected_tags))
      for tag, value in expected_tags.items():
        result += api.post_check(post_process.TagEquals, step_i, tag, value)

    return result


  step_passed = functools.partial(api.post_check, post_process.StepSuccess)
  step_failed = functools.partial(api.post_check, post_process.StepFailure)

  yield api.test(
      'full-run',
      api.properties(**{'$chromeos/signing': SigningProperties(timeout=5)}),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _PASSED, run=2),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          None, retcode=1),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _RUNNING, run=2),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _PASSED, run=3),
      step_passed('verify results.parse metadata'),
      check_metadata('verify results', [_PASSED_COMPLETE, _PASSED_COMPLETE]),
      api.post_check(
          post_process.PropertyEquals, 'signing_summary', {
              'gs://bucket/directory1/directory2/releases/file1.instructions':
                  'PASSED',
              'gs://bucket/directory1/directory2/releases/file2.instructions':
                  'PASSED'
          }),
      api.post_check(post_process.MustRun,
                     'wait for signing to complete.sleep 300'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-sleep-if-first-poll-succeeds',
      api.signing.set_timeout(5),
      api.signing.mock_signing_successes([
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          'gs://bucket/directory1/directory2/releases/file2.instructions.json'
      ]),
      step_passed('verify results.parse metadata'),
      check_metadata('verify results', [_PASSED_COMPLETE, _PASSED_COMPLETE]),
      api.post_check(post_process.DoesNotRun,
                     'wait for signing to complete.sleep 300'),
      api.post_process(post_process.DropExpectation),
  )

  # Timeout test.
  yield api.test(
      'times-out',
      api.properties(
          **{'$chromeos/signing': SigningProperties(timeout=5)}),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),  # Never succeeds.
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          None),  # Never starts.
      step_passed('verify results.parse metadata'),
      check_metadata(
          'verify results',
          # Until a signing is finalized it won't populate the meta map.
          [None, None]),
      step_failed('verify results'),
      api.post_check(
          post_process.PropertyEquals, 'signing_summary', {
              'gs://bucket/directory1/directory2/releases/file1.instructions':
                  'TIMED_OUT',
              'gs://bucket/directory1/directory2/releases/file2.instructions':
                  'TIMED_OUT'
          }),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Failed test.
  yield api.test(
      'signing-failed',
      api.properties(**{'$chromeos/signing': SigningProperties(timeout=5)}),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _PASSED, run=2),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _RUNNING),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _FAILED, run=2),
      step_passed('verify results.parse metadata'),
      check_metadata('verify results', [_PASSED_COMPLETE, _FAILED_COMPLETE]),
      step_failed('verify results'),
      api.post_check(
          post_process.PropertyEquals, 'signing_summary', {
              'gs://bucket/directory1/directory2/releases/file1.instructions':
                  'PASSED',
              'gs://bucket/directory1/directory2/releases/file2.instructions':
                  'FAILED'
          }),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Failed test with ImageAlreadyExistsError error.
  yield api.test(
      'signing-failed-already-exists',
      api.properties(
          **{
              '$chromeos/signing':
                  SigningProperties(timeout=5, ignore_already_exists_errors=True
                                   )
          }),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _PASSED, run=2),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _RUNNING),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _FAILED_ALREADY_EXISTS, run=2),
      step_passed('verify results.parse metadata'),
      check_metadata('verify results',
                     [_PASSED_COMPLETE, _FAILED_ALREADY_EXISTS_COMPLETE]),
      step_passed('verify results'),
      api.post_check(
          post_process.PropertyEquals, 'signing_summary', {
              'gs://bucket/directory1/directory2/releases/file1.instructions':
                  'PASSED',
              'gs://bucket/directory1/directory2/releases/file2.instructions':
                  'PREVIOUSLY_PASSED'
          }),
      api.post_process(post_process.DropExpectation),
  )

  # Malformed json
  yield api.test(
      'malformed-json',
      api.properties(**{'$chromeos/signing': SigningProperties(timeout=5)}),
      # Bad json (missing closing brace).
      api.signing.mock_meta_str(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          '{"value": "blah'),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _PASSED),
      step_passed('verify results.parse metadata'),
      # Verify that the good metadata makes it way in.
      check_metadata('verify results', [None, _PASSED_COMPLETE]),
      step_failed('verify results'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  api.signing.setup_mocks()
