# Copyright 2019 The ChromiumOS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api

import json


class SkylabTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def example_result(self, test_suite):
    if not hasattr(self, '_task_id'):
      self._task_id = 0
    else:
      self._task_id += 1

    return json.dumps({
        'task_name': test_suite,
        'task_id': self._task_id,
        'task_url': 'http://s.com/%s' % str(self._task_id)
    })

  def simulated_create_suites(self, name, test_unit):
    result = recipe_test_api.TestData()

    for test in test_unit.hw_test_cfg.hw_test:
      result += self.override_step_data(
          '%s.%s' % (name, test.suite), stdout=self.m.raw_io.output(
              self.example_result(test.suite)))
    return result
