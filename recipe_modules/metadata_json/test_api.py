# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class MetadataJsonTestApi(recipe_test_api.RecipeTestApi):
  """A module for testing metadata_json."""

  led_build_id = 8784717183252430977

  def test_builder(self, build_target_name, **kwargs):
    """Step data for a test builder.

    Args:
      build_target_name (str): Name of the build target, or None for no build
          target.
      kwargs (dict): arguments to pass to test_util.test_build.

    Returns:
      A step_data object with both the build and the simulated_get response.
    """
    build = self.m.test_util.test_child_build(build_target_name, **kwargs)
    return build.build + self.m.buildbucket.simulated_get(build.message)
