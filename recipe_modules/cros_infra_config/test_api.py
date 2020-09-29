# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from recipe_engine import recipe_test_api
from google.protobuf import json_format as jsonpb

from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.dut_tracking import TrackingPolicyCfg
from PB.testplans.test_retry import SuiteRetryCfg


class CrosInfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the infra_config module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def _read_config(self, filename, message):
    """Read the content of a json file in this directory.

    Args:
      filename (str): The basename of the file (located in this directory) to
          read.
      message (protobuf): A protocol buffer message to merge into.

    Returns:
      (str): The contents of the file, stripped.
    """
    with open(
        os.path.join(os.path.abspath(os.path.dirname(__file__)),
                     filename)) as f:
      data = f.read().strip()
    msg = jsonpb.Parse(data, message)
    return self.m.depot_gitiles.make_encoded_file(msg.SerializeToString())

  def builder_configs_step_test_data(self):
    """A function for step_test_data to generate BuilderConfigs."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_builder_configs.json', BuilderConfigs())

  def bot_policy_test_data(self):
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config.json', BotPolicyCfg())

  def vm_retry_test_data(self):
    """A function for step_test_data to generate SuiteRetryCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_vm_retry_config.json', SuiteRetryCfg())

  def dut_tracking_test_data(self):
    """A function for step_test_data to generate TrackingPolicyCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_dut_tracking_config.json',
                             TrackingPolicyCfg())

  def override_builder_configs_test_data(self, message, iteration=1):
    """Set arbitrary builder config test data.

    Args:
      message (BuilderConfigs): The data to return.
      iteration (int): Which call to read builder configs to replace.

    Returns:
      (StepTestData) to overwrite that BuilderConfigs refresh.
    """
    step_name = ('read builder configs'
                 if iteration == 1 else 'read builder configs (%d)' % iteration)
    step_name += '.fetch master:generated/builder_configs.binaryproto'
    return self.step_data(
        step_name,
        self.m.depot_gitiles.make_encoded_file(message.SerializeToString()))

  def current_builder_group(self, group):
    """Set the builder group for the currently running builder.

    This also sets the legacy mastername property so existing code
    continues to work.
    """
    # TODO(https://crbug.com/1109276) Do not set the mastername property
    return self.m.properties(builder_group=group, mastername=group)

  def parent_builder_group(self, group):
    """Set the builder group for the parent builder."""
    return self.m.properties(parent_builder_group=group)

  def target_builder_group(self, group):
    """Set the builder group for the target builder.

    This is used by findit, which has a single builder that performs
    bisection using the configuration of another builder.
    """
    return self.m.properties(target_builder_group=group)
