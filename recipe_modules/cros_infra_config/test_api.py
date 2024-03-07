# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Testing module for cros_infra_config."""

import os

from google.protobuf import json_format
from google.protobuf import message
from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.dut_tracking import TrackingPolicyCfg
from PB.chromiumos.test.api import pre_test_service as pre_request
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.testplans.test_retry import SuiteRetryCfg
from recipe_engine import recipe_test_api


class CrosInfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the infra_config module."""

  def _read_config(self, filename: str,
                   msg: message.Message) -> recipe_test_api.StepTestData:
    """Read the content of a json file in this directory.

    Args:
      filename: The basename of the file (located in this directory) to read.
      msg: A protocol buffer message to merge into.

    Returns:
      A StepTestData containing a JSON-like string with a single key 'value',
      whose value is the contents of the file, stripped.
    """
    with open(
        os.path.join(os.path.abspath(os.path.dirname(__file__)), filename),
        encoding='utf-8') as f:
      data = f.read().strip()
    msg = json_format.Parse(data, msg)
    return self.m.depot_gitiles.make_encoded_file_from_bytes(
        msg.SerializeToString())

  def _read_txt(self, filename: str) -> recipe_test_api.StepTestData:
    """Read the content of a txt file in this directory.

    Args:
      filename: the basename of the file (located in this directory) to read.

    Returns:
      A StepTestData containing a txt string.
    """
    with open(
        os.path.join(os.path.abspath(os.path.dirname(__file__)), filename),
        encoding='utf-8') as f:
      data = f.read().strip().encode('utf-8')
    return self.m.depot_gitiles.make_encoded_file_from_bytes(data)

  @property
  def builder_configs_test_data(self) -> BuilderConfigs:
    """BuilderConfigs message containing the standard test builders."""
    with open(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'test_builder_configs.json'), encoding='utf-8') as f:
      data = f.read().strip()
    return json_format.Parse(data, BuilderConfigs())

  def builder_configs_step_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate BuilderConfigs."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_builder_configs.json', BuilderConfigs())

  def realms_cfg_step_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate LUCI realms."""
    with open(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'test_model_realms.cfg'), encoding='utf-8') as f:
      data = f.read().strip()
    return self.m.depot_gitiles.make_encoded_file(data)

  def bot_policy_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config.json', BotPolicyCfg())

  def bot_policy_test_data_chrome(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config_chrome.json',
                             BotPolicyCfg())

  def bot_policy_test_data_chromeos_mpa(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config_chromeos_mpa.json',
                             BotPolicyCfg())

  def bot_policy_test_data_missing_fallback(
      self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config(
        'test_bot_policy_config_missing_fallback.json',  # pragma: nocover
        BotPolicyCfg())

  def vm_retry_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate SuiteRetryCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_vm_retry_config.json', SuiteRetryCfg())

  def test_filter_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate SuiteRetryCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_test_filter_config.json',
                             pre_request.FilterCfgs())  # pragma: no cover

  def ctp2_pools_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate ctp2 pools config."""
    # Humans can edit the txt file for test data.
    return self._read_txt('test_ctp2_pools_config.txt')

  def dut_tracking_test_data(self) -> recipe_test_api.StepTestData:
    """A function for step_test_data to generate TrackingPolicyCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_dut_tracking_config.json',
                             TrackingPolicyCfg())

  def override_builder_configs_test_data(
      self, msg: BuilderConfigs, iteration: int = 1, ref: str = 'HEAD',
      binaryproto: bool = True,
      step_name: str = '') -> recipe_test_api.TestData:
    """Set arbitrary builder config test data.

    Args:
      msg: The data to return.
      iteration: Which call to read builder configs to replace.
      ref: The ref from which the recipe is fetching builder configs.
      binaryproto: Whether this is a binaryproto read. (Default)
      step_name: Step name calling configure_builder().

    Returns:
      Test data to overwrite that BuilderConfigs refresh.
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
              msg.SerializeToString()))

    return self.step_data(
        step_name,
        self.m.depot_gitiles.make_encoded_file(json_format.MessageToJson(msg)))

  def use_custom_builder_config(self, custom_builder_config: BuilderConfig,
                                **kwargs) -> recipe_test_api.TestData:
    """Provide TestData to allow a test case to use a custom BuilderConfig.

    This is a convenience function for test cases that just need to specify
    certain BuilderConfig properties. If the test case has more complex needs,
    such as multiple BuilderConfigs or a fancier buildbucket.build, then it
    should use a more robust option like override_builder_configs_test_data().

    Internally, this overrides the test data for BuilderConfigs to contain
    only custom_builder_config. Then it sets the test case's buildbucket.build
    so that the build will find and use the specified config.

    If the BuilderConfig.Id does not specify a name, it will be set to an
    innocuous default value: 'custom-builder'. As a corollary, the
    buildbucket.build will use that name, too.

    Args:
      custom_builder_config: The BuilderConfig for this test case.
      kwargs: Additional kwargs to pass into override_builder_configs_test_data.
        Hint: For many builders, configs are loaded during a step named either
        "configure builder" or "configure builder.cros_infra_config". You'll
        probably want to use the `step_name` kwarg.
    """
    builder_configs = BuilderConfigs()
    builder_config = builder_configs.builder_configs.add()
    builder_config.CopyFrom(custom_builder_config)
    if not builder_config.id.name:
      builder_config.id.name = 'custom-builder'
    return (self.override_builder_configs_test_data(builder_configs, **kwargs) +
            self.m.buildbucket.build(
                build_pb2.Build(
                    builder=builder_common_pb2.BuilderID(
                        builder=builder_config.id.name,
                        bucket=builder_config.id.bucket,
                        project='chromeos',
                    ))))
