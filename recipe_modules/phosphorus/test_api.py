# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusEnvProperties


class PhosphorusTestApi(recipe_test_api.RecipeTestApi):
  """Test data for phosphorus api."""

  def properties(self, dut_name=None):
    """Gets properties to pass to api.test().

    For use in recipes and modules using phosphorus.
    """
    if not dut_name:  # pragma: nocover
      dut_name = 'placeholder-dut-name'
    return self.m.properties(
        **{
            '$chromeos/phosphorus':
                PhosphorusProperties(
                    version=PhosphorusProperties.Version(
                        cipd_label='some-cipd-label',
                    ), config={
                        'admin_service': 'foo-service',
                        'cros_inventory_service': 'inv-service',
                        'cros_ufs_service': 'ufs-service',
                        'autotest_dir': '/path/to/autotest',
                    }),
        }) + self.m.properties.environ(
            PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-' + dut_name,
                                    SWARMING_TASK_ID='placeholder-task-id',
                                    SKYLAB_DUT_ID='placeholder-dut-id'))
