# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import structs

from recipe_engine import recipe_test_api

from PB.chromiumos.common import BuildTarget
from PB.testplans.generate_test_plan import BuildPayload
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon


class SkylabTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def create_suite_json_output(self, label):
    return {
        'task_id': '%s-task-id' % label,
        'task_url': 'https://swarming.com/%s' % label,
    }

  def wait_tasks_json_output(self):
    # TODO(akeshet): Use a skylab_tool.Result proto here, instead of
    # handcrafted dict.
    return {'results':
        [{
            "task-result": {
                "name": "a test",
                "state": "",
                "failure": False,
                "success": True,
                "task-request-id": "ID",
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
            "task-request-id": id,
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
    return structs.SkylabTask(
        id=id or 'task-id',
        url=url or 'https://google.com',
        test=test,
        unit=unit)

  def skylab_result(self, task=None, success=True, output=None):
    return structs.SkylabResult(
        task=task or self.skylab_task(),
        success=success,
        output=output or 'Successfully ran all tests!',
    )  # pragma: no cover
