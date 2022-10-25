# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Success workflow tests for the signing recipe module."""

import functools

from PB.recipe_modules.chromeos.signing.signing import SigningProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

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

_PASSED_COMPLETE = {
    'release_directory': 'directory1/directory2/releases',
    'status': {
        'status': 'passed'
    },
}
_FAILED_COMPLETE = {
    'release_directory': 'directory1/directory2/releases',
    'status': {
        'status': 'failed',
        'details': 'failed for reason foo'
    },
}


def RunSteps(api):
  metadata = api.signing.wait_for_signing([
      'gs://bucket/directory1/directory2/releases/file1.instructions',
      'gs://bucket/directory1/directory2/releases/file2.instructions'
  ])
  with api.step.nest("verify results") as child_step:
    child_step.step_summary_text = api.signing.get_signed_build_metadata(
        metadata)
    api.signing.verify_signing_success(metadata, child_step)


def GenTests(api):

  def StepMetaEquals(check, step_odict, step, expected):
    """Check that the step's meta_list equals given value.

    Assumes order does not matter.

    Args:
      step (str) - The step to check the meta_list of.
      expected (array) - The expected value of the meta_list.

    Usage:
      yield TEST + \
          api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    # Verify arrays same size.
    check(len(step_odict[step].step_summary_text) == len(expected))
    # Verify arrays same contents.
    for elem in expected:
      check(
          expected.count(elem) == step_odict[step].step_summary_text.count(
              elem))

  step_passed = functools.partial(api.post_check, post_process.StepSuccess)
  step_failed = functools.partial(api.post_check, post_process.StepFailure)

  yield api.test(
      'full-run',
      api.properties(**{"$chromeos/signing": SigningProperties(timeout=5)}),
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
      api.post_check(StepMetaEquals, 'verify results',
                     [_PASSED_COMPLETE, _PASSED_COMPLETE]),
      api.post_check(post_process.MustRun,
                     'wait for signing to complete.sleep 300'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-sleep-if-first-poll-succeeds',
      api.properties(**{"$chromeos/signing": SigningProperties(timeout=5)}),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _PASSED),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _PASSED),
      step_passed('verify results.parse metadata'),
      api.post_check(StepMetaEquals, 'verify results',
                     [_PASSED_COMPLETE, _PASSED_COMPLETE]),
      api.post_check(post_process.DoesNotRun,
                     'wait for signing to complete.sleep 300'),
      api.post_process(post_process.DropExpectation),
  )

  # Timeout test.
  yield api.test(
      'times-out',
      api.properties(
          **{"$chromeos/signing": SigningProperties(timeout=5)}),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),  # Never succeeds.
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          None),  # Never starts.
      step_passed('verify results.parse metadata'),
      api.post_check(
          StepMetaEquals,
          'verify results',
          # Until a signing is finalized it won't populate the meta map.
          [None, None]),
      step_failed('verify results'),
      api.post_process(post_process.DropExpectation),
  )

  # Failed test.
  yield api.test(
      'signing-failed',
      api.properties(**{"$chromeos/signing": SigningProperties(timeout=5)}),
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
      api.post_check(StepMetaEquals, 'verify results',
                     [_PASSED_COMPLETE, _FAILED_COMPLETE]),
      step_failed('verify results'),
      api.post_process(post_process.DropExpectation),
  )

  # Malformed json
  yield api.test(
      'malformed-json',
      api.properties(**{"$chromeos/signing": SigningProperties(timeout=5)}),
      # Bad json (missing closing brace).
      api.signing.mock_meta_str(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          '{"value": "blah'),
      api.signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _PASSED),
      step_passed('verify results.parse metadata'),
      # Verify that the good metadata makes it way in.
      api.post_check(StepMetaEquals, 'verify results',
                     [_PASSED_COMPLETE, None]),
      step_failed('verify results'),
      api.post_process(post_process.DropExpectation),
  )

  api.signing.setup_mocks()
