# Copyright 2019 The ChromiumOS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class EasyTestApi(recipe_test_api.RecipeTestApi):
  """Simulate test data for easy api."""

  def simulate_json_step(self, step_name, data):
    return self.step_data(step_name, self.m.json.output_stream(data))
