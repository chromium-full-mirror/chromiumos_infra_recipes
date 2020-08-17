# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosSourceTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_source module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def test(self, name, *args, **kwargs):
    """Create a test with properties.

    Args:
      cros_source_properties (dict): module properties for cros_source.
      args (list): args for api.test()
      kwargs (dict): kwargs for api.test_util.test_build.  Defaults applied:
        - cq = True.
        - revision = arbitrary sha.
        - git_repo = internal manifest url.

    Returns:
      (TestData) the build with cros_source properties included.
    """
    kwargs = kwargs or {}
    cros_source_properties = kwargs.pop('cros_source_properties', {})
    kwargs.setdefault('cq', True)
    kwargs.setdefault('revision', '2d72510e447ab60a9728aeea2362d8be2cbd7789')
    kwargs.setdefault('git_repo', self.m.src_state.internal_manifest.url)

    data = self.m.test_util.test_build(**kwargs).build
    if cros_source_properties:
      data += self.m.properties(
          **{'$chromeos/cros_source': cros_source_properties})

    return super(CrosSourceTestApi, self).test(name, data, *args)
