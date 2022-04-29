# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Success workflow tests for the cros_signing recipe module."""
import functools

from PB.recipe_modules.chromeos.cros_signing.cros_signing import \
  CrosSigningProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine import post_process

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
        'status': 'failed'
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
        'status': 'failed'
    },
}


def RunSteps(api):
  metadata = api.cros_signing.wait_for_signing([
      'gs://bucket/directory1/directory2/releases/file1.instructions',
      'gs://bucket/directory1/directory2/releases/file2.instructions'
  ])
  with api.step.nest("verify results") as child_step:
    child_step.step_summary_text = api.cros_signing.get_signed_build_metadata(
        metadata)
    api.cros_signing.verify_signing_success(metadata)


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
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _PASSED, run=2),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          None, retcode=1),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _RUNNING, run=2),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _PASSED, run=3),
      step_passed('verify results.parse metadata'),
      api.post_check(StepMetaEquals, 'verify results',
                     [_PASSED_COMPLETE, _PASSED_COMPLETE]),
      api.post_process(post_process.DropExpectation),
  )

  # Timeout test.
  yield api.test(
      'times-out',
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),  # Never succeeds.
      api.cros_signing.mock_meta(
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
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _RUNNING),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          _PASSED, run=2),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _RUNNING),
      api.cros_signing.mock_meta(
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
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      # Bad json (missing closing brace).
      api.cros_signing.mock_meta_str(
          'gs://bucket/directory1/directory2/releases/file1.instructions.json',
          '{"value": "blah'),
      api.cros_signing.mock_meta(
          'gs://bucket/directory1/directory2/releases/file2.instructions.json',
          _PASSED),
      step_passed('verify results.parse metadata'),
      # Verify that the good metadata makes it way in.
      api.post_check(StepMetaEquals, 'verify results',
                     [_PASSED_COMPLETE, None]),
      step_failed('verify results'),
      api.post_process(post_process.DropExpectation),
  )

  api.cros_signing.setup_mocks()
