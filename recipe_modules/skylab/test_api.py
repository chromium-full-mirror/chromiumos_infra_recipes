# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import structs

from recipe_engine import recipe_test_api

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

  def hw_test(self, name=None, suite=None, board=None, critical=True):
    return HwTestCfg.HwTest(
        common=TestSuiteCommon(
            display_name=name or 'target.hw.bvt-cq',
            critical={'value': critical},
        ),
        suite=suite or 'bvt-cq',
        skylab_board=board or 'target',
    )

  def skylab_task(self, id=None, url=None, test=None):
    return structs.SkylabTask(
        id=id or 'task-id',
        url=url or 'https://google.com',
        test=test or self.hw_test())

  def skylab_result(self, task=None, success=True, output=None):
    return structs.SkylabResult(
        task=task or self.skylab_task(),
        success=success,
        output=output or 'Successfully ran all tests!',
    )
