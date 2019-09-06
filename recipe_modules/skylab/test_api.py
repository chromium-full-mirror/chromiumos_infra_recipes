# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import structs

from recipe_engine import recipe_test_api

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon

from google.protobuf import struct_pb2
from google.protobuf import json_format


class SkylabTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def create_suite_json_output(self, label):
    # Really ugly. Should be deleted with create_suite().
    if label == 'bvt-cq':
      task_id = 1234
    else:  # pragma: no cover
      task_id = 4321
    return {
        'task_id': task_id,
        'task_url': 'https://swarming.com/%s' % label,
    }

  def wait_tasks_json_output(self):
    # TODO(akeshet): Use a skylab_tool.Result proto here, instead of
    # handcrafted dict.
    return {
        'results': [{
            "task-result": {
                "name": "a test",
                "state": "",
                "failure": False,
                "success": True,
                "task-request-id": "1234",
                "task-run-url": "http://example.com",
                "task-logs-url": "http://example.log"
            },
            "stdout": "",
            "child-results": None
        }]
    }

  def wait_task_result(self, id, name, success=True):
    return {
        "task-result": {
            "name": name,
            "state": "",
            "failure": not success,
            "success": success,
            "task-request-id": str(id),
            "task-run-url": "http://example.com",
            "task-logs-url": "http://example.log"
        },
        "stdout": "",
        "child-results": None
    }  # pragma: no cover

  def hw_test_unit(self, common=None, hw_tests=None):
    if common is None:
      common = TestUnitCommon(
          build_target=BuildTarget(name='build_target_name'),
          build_payload=BuildPayload(
              artifacts_gs_bucket='gsbucket',
              artifacts_gs_path='gspath',
          ),
      )
    if hw_tests is None:
      hw_test_cfg = HwTestCfg(hw_test=[self.hw_test()]) # pragma: no cover
    else:
      hw_test_cfg = HwTestCfg(hw_test=hw_tests)
    return HwTestUnit(common=common, hw_test_cfg=hw_test_cfg)

  def hw_test(self, name=None, suite=None, board=None, critical=True):
    return HwTestCfg.HwTest(
        common=TestSuiteCommon(
            display_name=name or 'target.hw.bvt-cq',
            critical={'value': critical},
        ),
        suite=suite or 'bvt-cq',
        skylab_board=board or 'target',
    )

  def skylab_task(self, id=None, url=None, test=None, unit=None):
    if test is None and unit is None:
      unit = self.hw_test_unit() # pragma: no cover
      test = unit.hw_test_cfg.hw_test[0] # pragma: no cover
    elif test is None:
      test = unit.hw_test_cfg.hw_test[0] # pragma: no cover
    else:
      unit = self.hw_test_unit(hw_tests=[test])
    return structs.SkylabTask(id=id or 1234, url=url or 'https://google.com',
                              test=test, unit=unit)

  def skylab_result(self, task=None, success=True, child_results=None):
    return structs.SkylabResult(
        task=task or self.skylab_task(),
        success=success,
        child_results=child_results or [],
    )  # pragma: no cover

  def response(self, success=False):
    json_string = """
{
  "response": {
      "state": {
          "verdict": "%s",
          "lifeCycle": "LIFE_CYCLE_COMPLETED"
      },
      "taskResults": [
          {
              "state": {
                  "verdict": "VERDICT_PASSED",
                  "lifeCycle": "LIFE_CYCLE_COMPLETED"
              },
              "taskUrl": "https://chromeos-swarming.appspot.com/task?id=471a63bc9c481010",
              "name": "cheets_NotificationTest",
              "logUrl": "https://stainless.corp.google.com/browse/chromeos-autotest-results/swarming-471a63bc9c481010/"
          }
      ]
  }
}"""
    verdict = 'VERDICT_PASSED' if success else 'VERDICT_FAILED'
    response_struct = struct_pb2.Struct()
    return json_format.Parse(json_string % verdict, response_struct)

  def test_with_execute_response(self, id, success=False):
    return build_pb2.Build(
        id=id, output=build_pb2.Build.Output(properties=self.response(success)))
