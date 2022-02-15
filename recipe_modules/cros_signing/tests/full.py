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


def RunSteps(api):
  metadata = api.cros_signing.wait_for_signing(['gs://file1', 'gs://file2'])
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
    check(sorted(step_odict[step].step_summary_text) == sorted(expected))

  step_passed = functools.partial(api.post_check, post_process.StepSuccess)
  step_failed = functools.partial(api.post_check, post_process.StepFailure)

  yield api.test(
      'full run',
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      api.cros_signing.mock_meta('gs://file1.json', _RUNNING),
      api.cros_signing.mock_meta('gs://file1.json', _PASSED, run=2),
      api.cros_signing.mock_meta('gs://file2.json', None, retcode=1),
      api.cros_signing.mock_meta('gs://file2.json', _RUNNING, run=2),
      api.cros_signing.mock_meta('gs://file2.json', _PASSED, run=3),
      step_passed('verify results.parse metadata'),
      api.post_check(StepMetaEquals, 'verify results', [_PASSED, _PASSED]),
  )

  # Timeout test.
  yield api.test(
      'times out',
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      api.cros_signing.mock_meta('gs://file1.json',
                                 _RUNNING),  # Never succeeds.
      api.cros_signing.mock_meta('gs://file2.json', None),  # Never starts.
      step_passed('verify results.parse metadata'),
      api.post_check(
          StepMetaEquals,
          'verify results',
          # Until a signing is finalized it won't populate the meta map.
          [None, None]),
      step_failed('verify results'))

  # Failed test.
  yield api.test(
      'signing failed',
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      api.cros_signing.mock_meta('gs://file1.json', _RUNNING),
      api.cros_signing.mock_meta('gs://file1.json', _PASSED, run=2),
      api.cros_signing.mock_meta('gs://file2.json', _RUNNING),
      api.cros_signing.mock_meta('gs://file2.json', _FAILED, run=2),
      step_passed('verify results.parse metadata'),
      api.post_check(StepMetaEquals, 'verify results', [_PASSED, _FAILED]),
      step_failed('verify results'))

  # Malformed json
  yield api.test(
      'malformed json',
      api.properties(
          **{"$chromeos/cros_signing": CrosSigningProperties(timeout=5)}),
      # Bad json (missing closing brace).
      api.cros_signing.mock_meta_str('gs://file1.json', '{"value": "blah'),
      api.cros_signing.mock_meta('gs://file2.json', _PASSED),
      step_passed('verify results.parse metadata'),
      # Verify that the good metadata makes it way in.
      api.post_check(StepMetaEquals, 'verify results', [_PASSED, None]),
      step_failed('verify results'))

  api.cros_signing.setup_mocks()
