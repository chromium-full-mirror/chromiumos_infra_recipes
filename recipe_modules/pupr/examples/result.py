# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for StepResult and Result in pupr."""

from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from RECIPE_MODULES.chromeos.pupr.api import format_gerrit_change_link
from RECIPE_MODULES.chromeos.pupr.api import Result
from RECIPE_MODULES.chromeos.pupr.api import StepResult
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'pupr',
]


def RunSteps(api: recipe_api.RecipeApi):
  # Test format_gerrit_change_link
  c_chromium = GerritChange(host='chromium-review.googlesource.com', change=123,
                            project='chromium/src')
  c_internal = GerritChange(host='chrome-internal-review.googlesource.com',
                            change=456, project='chromeos/manifest-internal')
  c_custom = GerritChange(host='custom.googlesource.com', change=789)

  api.assertions.assertEqual(
      api.pupr.format_gerrit_change_link(c_chromium),
      '[chromium:123](https://crrev.com/c/123)')
  api.assertions.assertEqual(
      api.pupr.format_gerrit_change_link(c_internal),
      '[chrome-internal:456](https://crrev.com/i/456)')
  api.assertions.assertEqual(
      api.pupr.format_gerrit_change_link(c_custom), '789')
  api.assertions.assertEqual(
      format_gerrit_change_link(c_chromium),
      '[chromium:123](https://crrev.com/c/123)')

  # Test record and evaluate: creation success with cleanup errors demoted to warnings
  r1 = Result()
  step1 = StepResult(value=42, created=[c_chromium], retried=[c_internal],
                     abandoned=[c_custom], errors=['cannot set Verified-1'],
                     warnings=['minor warning'])
  val1 = r1.record(step1)
  api.assertions.assertEqual(val1, 42)
  status1, summary1 = r1.evaluate(is_retry_only=False)
  api.assertions.assertEqual(status1, bb_common_pb2.SUCCESS)
  api.assertions.assertTrue(summary1.startswith('success\n'))
  api.assertions.assertIn(
      '### Created CLs\n* [chromium:123](https://crrev.com/c/123)', summary1)
  api.assertions.assertIn(
      '### Retried CLs\n* [chrome-internal:456](https://crrev.com/i/456)',
      summary1)
  api.assertions.assertIn('### Abandoned CLs\n* 789', summary1)
  api.assertions.assertIn('### Warnings', summary1)
  api.assertions.assertIn('* cannot set Verified-1', summary1)
  api.assertions.assertIn('* minor warning', summary1)

  # Test record and evaluate: retry-only run promotes cleanup errors to errors
  r2 = Result()
  r2.record(StepResult(value=None, errors=['retry cleanup failed']))
  status2, summary2 = r2.evaluate(is_retry_only=True)
  api.assertions.assertEqual(status2, bb_common_pb2.FAILURE)
  api.assertions.assertIn('[retry-only] failed: retry cleanup failed', summary2)
  api.assertions.assertIn('### Errors', summary2)

  # Test fatal errors
  r3 = Result(fatal_errors=['fatal error occurred'])
  status3, summary3 = r3.evaluate()
  api.assertions.assertEqual(status3, bb_common_pb2.FAILURE)
  api.assertions.assertIn('failed: fatal error occurred', summary3)

  # Test retried section when only retried
  r4 = Result()
  r4.record(StepResult(value=None, retried=[c_chromium]))
  status4, summary4 = r4.evaluate(is_retry_only=True)
  api.assertions.assertEqual(status4, bb_common_pb2.SUCCESS)
  api.assertions.assertTrue(summary4.startswith('[retry-only] success\n'))
  api.assertions.assertIn(
      '### Retried CLs\n* [chromium:123](https://crrev.com/c/123)', summary4)

  # Test abandoned section when only abandoned
  r5 = Result()
  r5.record(StepResult(value=None, abandoned=[c_internal]))
  status5, summary5 = r5.evaluate(is_retry_only=True)
  api.assertions.assertEqual(status5, bb_common_pb2.SUCCESS)
  api.assertions.assertTrue(summary5.startswith('[retry-only] success\n'))
  api.assertions.assertIn(
      '### Abandoned CLs\n* [chrome-internal:456](https://crrev.com/i/456)',
      summary5)

  # Test no action reason
  r6 = Result(no_action_reason='no modified projects')
  status6, summary6 = r6.evaluate()
  api.assertions.assertEqual(status6, bb_common_pb2.SUCCESS)
  api.assertions.assertEqual(summary6, 'no action (no modified projects)')

  # Test default success
  r7 = Result()
  status7, summary7 = r7.evaluate()
  api.assertions.assertEqual(status7, bb_common_pb2.SUCCESS)
  api.assertions.assertEqual(summary7, 'success')

  # Test record(Result) merges into parent Result
  r_parent = Result()
  r_child = Result(
      created=[c_chromium],
      retried=[c_internal],
      abandoned=[c_custom],
      cleanup_errors=['err1'],
      fatal_errors=['err2'],
      warnings=['warn1'],
      errors=['err3'],
      no_action_reason='child reason',
  )
  rec_val = r_parent.record(r_child)
  api.assertions.assertIsNone(rec_val)
  api.assertions.assertEqual(r_parent.created, [c_chromium])
  api.assertions.assertEqual(r_parent.retried, [c_internal])
  api.assertions.assertEqual(r_parent.abandoned, [c_custom])
  api.assertions.assertEqual(r_parent.cleanup_errors, ['err1'])
  api.assertions.assertEqual(r_parent.fatal_errors, ['err2'])
  api.assertions.assertEqual(r_parent.warnings, ['warn1'])
  api.assertions.assertEqual(r_parent.errors, ['err3'])
  api.assertions.assertEqual(r_parent.no_action_reason, 'child reason')


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )
