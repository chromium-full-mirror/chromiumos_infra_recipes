# Copyright 2019 The ChromiumOS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
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

  def skylab_task(self, id=None, test=None):
    return structs.SkylabTask(
        id=id or 'task-id',
        test=test or HwTestCfg.HwTest(
            common=TestSuiteCommon(display_name='target.hw.bvt-cq'),
            suite='bvt-cq',
            skylab_board='target',
            critical=True,
        ),
    )

  def skylab_result(self, task=None, success=True, output=None):
    return structs.SkylabResult(
        task=task or self.skylab_task(),
        success=success,
        output=output or 'Successfully ran all tests!',
    )
