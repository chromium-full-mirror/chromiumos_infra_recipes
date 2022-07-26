# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import \
  CrosToolRunnerProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import \
  CrosToolRunnerEnvProperties


class CrosToolRunnerTestApi(recipe_test_api.RecipeTestApi):
  """Test data for CrosToolRunner api."""

  def properties(self, bot_id=None, bot_is_dut=False):
    """Gets properties to pass to api.test().

    For use in recipes and modules using cros_tool_runner.
    """
    if not bot_id:  # pragma: nocover
      bot_id = 'placeholder-bot-name'
    if bot_is_dut:
      bot_id = 'crossk-' + bot_id
    return self.m.properties(
        **{
            '$chromeos/cros_tool_runner':
                CrosToolRunnerProperties(
                    version=CrosToolRunnerProperties.Version(
                        cipd_label='some-cipd-label',
                    ))
        }) + self.m.properties.environ(
            CrosToolRunnerEnvProperties(SWARMING_BOT_ID=bot_id,
                                        SWARMING_TASK_ID='placeholder-task-id',
                                        SKYLAB_DUT_ID='placeholder-dut-id'))
