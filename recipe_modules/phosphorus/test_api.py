# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusEnvProperties


class PhosphorusTestApi(recipe_test_api.RecipeTestApi):
  """Test data for phosphorus api."""

  def properties(self, dut_name=None, bot_prefix=None):
    """Gets properties to pass to api.test().

    For use in recipes and modules using phosphorus.
    """
    config = {
        'admin_service': 'foo-service',
        'cros_inventory_service': 'inv-service',
        'cros_ufs_service': 'ufs-service',
        'autotest_dir': '/path/to/autotest',
    }
    if not dut_name:  # pragma: nocover
      dut_name = 'placeholder-dut-name'

    bot_id = ''
    if bot_prefix:
      config['bot_prefix'] = bot_prefix
      bot_id = bot_prefix + dut_name
    else:
      bot_id = dut_name

    return self.m.properties(
        **{
            '$chromeos/phosphorus':
                PhosphorusProperties(
                    version=PhosphorusProperties.Version(
                        cipd_label='some-cipd-label',
                    ), config=config),
        }) + self.m.properties.environ(
            PhosphorusEnvProperties(SWARMING_BOT_ID=bot_id,
                                    SWARMING_TASK_ID='placeholder-task-id',
                                    SKYLAB_DUT_ID='placeholder-dut-id'),
            CLOUDBOTS_DUT_HOSTNAME="placeholder-cloudbots-dut-hostname")
