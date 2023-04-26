# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
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
    return self.m.depot_gitiles.make_encoded_file_from_bytes(
        msg.SerializeToString())

  @property
  def builder_configs_test_data(self):
    """BuilderConfigs message containing the test builders."""
    with open(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'test_builder_configs.json')) as f:
      data = f.read().strip()
    return jsonpb.Parse(data, BuilderConfigs())

  def builder_configs_step_test_data(self):
    """A function for step_test_data to generate BuilderConfigs."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_builder_configs.json', BuilderConfigs())

  def realms_cfg_step_test_data(self):
    """A function for step_test_data to generate LUCI realms."""
    with open(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'test_model_realms.cfg')) as f:
      data = f.read().strip()
    return self.m.depot_gitiles.make_encoded_file(data)

  def bot_policy_test_data(self):
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config.json', BotPolicyCfg())

  def bot_policy_test_data_chrome(self):
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config_chrome.json',
                             BotPolicyCfg())

  def bot_policy_test_data_missing_fallback(self):
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config(
        'test_bot_policy_config_missing_fallback.json',  # pragma: nocover
        BotPolicyCfg())

  def vm_retry_test_data(self):
    """A function for step_test_data to generate SuiteRetryCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_vm_retry_config.json', SuiteRetryCfg())

  def dut_tracking_test_data(self):
    """A function for step_test_data to generate TrackingPolicyCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_dut_tracking_config.json',
                             TrackingPolicyCfg())

  def override_builder_configs_test_data(self, message, iteration=1, ref='HEAD',
                                         binaryproto=True, step_name=''):
    """Set arbitrary builder config test data.

    Args:
      message (BuilderConfigs): The data to return.
      iteration (int): Which call to read builder configs to replace.
      binaryproto (bool): Whether this is a binaryproto read. (Default)
      step_name (string): Step name calling configure_builder().

    Returns:
      (StepTestData) to overwrite that BuilderConfigs refresh.
    """
    step_name = '{}{}'.format(step_name + '.' if step_name else '',
                              ('read builder configs' if iteration == 1 else
                               'read builder configs (%d)' % iteration))
    step_name += '.fetch {}:generated/builder_configs.{}'.format(
        ref, 'binaryproto' if binaryproto else 'cfg')

    if binaryproto:
      return self.step_data(
          step_name,
          self.m.depot_gitiles.make_encoded_file_from_bytes(
              message.SerializeToString()))

    return self.step_data(
        step_name,
        self.m.depot_gitiles.make_encoded_file(jsonpb.MessageToJson(message)))
