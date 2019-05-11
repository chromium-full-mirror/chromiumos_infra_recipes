# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class TestPlanTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for vm_test api."""

  @property
  def swarming_server(self):
    return 'https://vm_swarming_server.com'

  @property
  def swarming_pool(self):
    return 'vm_pool'

  @property
  def swarming_role(self):
    return 'vm_role'
