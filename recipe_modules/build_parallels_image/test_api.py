# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.build_parallels_image.build_parallels_image \
  import BuildParallelsImageEnvProperties


class BuildParallelsImageTestApi(recipe_test_api.RecipeTestApi):
  """Test data for build_parallels_image api."""

  def environment(self, dut_name=None):
    """Gets dummy environment properties to pass to api.test().

    For use in recipes and modules using build_parallels_image."""
    if not dut_name:  # pragma: nocover
      dut_name = 'dummy-dut-name'
    return self.m.properties.environ(
        BuildParallelsImageEnvProperties(SWARMING_BOT_ID='crossk-' + dut_name))
