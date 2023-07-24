# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from google.protobuf import json_format as jsonpb
from google.protobuf.message import Message

from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.dut_tracking import TrackingPolicyCfg
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.testplans.test_retry import SuiteRetryCfg
from PB.chromiumos.test.api import pre_test_service as pre_request


class CrosInfraConfigTestApi(RecipeTestApi):
  """Helpers for testing the infra_config module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def _read_config(self, filename: str, message: Message) -> str:
    """Read the content of a json file in this directory.

    Args:
      filename: The basename of the file (located in this directory) to read.
      message: A protocol buffer message to merge into.

    Returns:
      A JSON-like string with a single key 'value', whose value is the contents
      of the file, stripped.
    """
    with open(
        os.path.join(os.path.abspath(os.path.dirname(__file__)),
                     filename)) as f:
      data = f.read().strip()
    msg = jsonpb.Parse(data, message)
    return self.m.depot_gitiles.make_encoded_file_from_bytes(
        msg.SerializeToString())

  @property
  def builder_configs_test_data(self) -> BuilderConfigs:
    """BuilderConfigs message containing the standard test builders."""
    with open(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'test_builder_configs.json')) as f:
      data = f.read().strip()
    return jsonpb.Parse(data, BuilderConfigs())

  def builder_configs_step_test_data(self) -> str:
    """A function for step_test_data to generate BuilderConfigs."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_builder_configs.json', BuilderConfigs())

  def realms_cfg_step_test_data(self) -> str:
    """A function for step_test_data to generate LUCI realms."""
    with open(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'test_model_realms.cfg')) as f:
      data = f.read().strip()
    return self.m.depot_gitiles.make_encoded_file(data)

  def bot_policy_test_data(self) -> str:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config.json', BotPolicyCfg())

  def bot_policy_test_data_chrome(self) -> str:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_bot_policy_config_chrome.json',
                             BotPolicyCfg())

  def bot_policy_test_data_missing_fallback(self) -> str:
    """A function for step_test_data to generate BotPolicies."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config(
        'test_bot_policy_config_missing_fallback.json',  # pragma: nocover
        BotPolicyCfg())

  def vm_retry_test_data(self) -> str:
    """A function for step_test_data to generate SuiteRetryCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_vm_retry_config.json', SuiteRetryCfg())

  def test_filter_test_data(self) -> str:
    """A function for step_test_data to generate SuiteRetryCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_test_filter_config.json',
                             pre_request.FilterCfgs())  # pragma: no cover

  def dut_tracking_test_data(self) -> str:
    """A function for step_test_data to generate TrackingPolicyCfg."""
    # Humans can edit the JSON file for test data, impl reads binary proto.
    return self._read_config('test_dut_tracking_config.json',
                             TrackingPolicyCfg())

  def override_builder_configs_test_data(self, message: BuilderConfigs,
                                         iteration: int = 1, ref: str = 'HEAD',
                                         binaryproto: bool = True,
                                         step_name: str = '') -> TestData:
    """Set arbitrary builder config test data.

    Args:
      message: The data to return.
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
              message.SerializeToString()))

    return self.step_data(
        step_name,
        self.m.depot_gitiles.make_encoded_file(jsonpb.MessageToJson(message)))

  def use_custom_builder_config(self, custom_builder_config: BuilderConfig,
                                **kwargs) -> TestData:
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
                        project="chromeos",
                    ))))
