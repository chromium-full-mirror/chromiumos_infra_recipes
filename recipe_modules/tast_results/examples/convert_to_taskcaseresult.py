# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format as jsonpb

from PB.test_platform.taskstate import TaskState
from PB.tast.test_result import TestResult

DEPS = [
    'recipe_engine/assertions',
    'tast_results',
]



def RunSteps(api):
  passed_test_result = jsonpb.Parse(
      '''
  {
    "name": "arc.Boot",
    "errors": [],
    "start": "2020-01-27T15:16:15.146771555-08:00",
    "end": "2020-01-27T15:16:33.420622341-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/arc.Boot",
    "skipReason": ""
  }
  ''', TestResult())
  failed_test_result = jsonpb.Parse(
      '''
  {
      "name": "arc.BuildProperties",
      "start": "2020-01-27T15:16:33.421007899-08:00",
      "end": "2020-01-27T15:16:36.833644627-08:00",
      "outDir": "/tmp/vm-test-results.JxZdcJ/tests/arc.BuildProperties",
      "skipReason": "",
      "errors": [
        {
          "reason": "failure"
        }
      ]
  }
  ''', TestResult())
  skipped_test_result = jsonpb.Parse(
      '''
  {
      "name": "arc.StartStop",
      "errors": [],
      "skipReason": "Felt like it."
  }
  ''', TestResult())
  passed_tcr = api.tast_results.convert_to_testcaseresult(passed_test_result)
  api.assertions.assertEqual(passed_tcr.verdict, TaskState.VERDICT_PASSED)
  failed_tcr = api.tast_results.convert_to_testcaseresult(failed_test_result)
  api.assertions.assertEqual(failed_tcr.verdict, TaskState.VERDICT_FAILED)
  api.assertions.assertEqual(failed_tcr.human_readable_summary, 'failure')
  skipped_tcr = api.tast_results.convert_to_testcaseresult(skipped_test_result)
  api.assertions.assertEqual(skipped_tcr.verdict, TaskState.VERDICT_NO_VERDICT)
  api.assertions.assertEqual(skipped_tcr.human_readable_summary,
                             'Felt like it.')


def GenTests(api):
  yield api.test('basic')
