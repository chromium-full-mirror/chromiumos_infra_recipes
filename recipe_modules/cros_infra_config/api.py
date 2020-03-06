# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format
from recipe_engine import recipe_api
from util import exponential_retry

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.builder_config import BuilderConfigs
from PB.testplans.test_retry import SuiteRetryCfg

REPO_URL = "https://chrome-internal.googlesource.com/chromeos/infra/config"


class CrosInfraConfigApi(recipe_api.RecipeApi):
  """A module for accessing data in the chromeos/infra/config repo"""

  def __init__(self, properties, *args, **kwargs):
    super(CrosInfraConfigApi, self).__init__(*args, **kwargs)
    # Map from BuilderConfig's id.name to BuilderConfig, lazily loaded.
    self._name_to_builder_config = {}

    # Save the properties message.
    self._properties = properties

    # Parse properties.config_ref
    self._config_ref = properties.config_ref or 'master'

  @property
  def props_for_child_build(self):
    """Return properties dict meant to be passed to child builds.

    Preserve $chromeos/cros_infra_config when launching a child build.
    """
    if not self._properties.config_ref:
      return {}
    msg = CrosInfraConfigProperties()
    msg.CopyFrom(self._properties)
    return {'$chromeos/cros_infra_config':
            json_format.MessageToDict(msg, preserving_proto_field_name=True)}

  @exponential_retry(retries=3, condition=lambda e: e.had_timeout)
  def _fetch_builder_configs(self):
    """Helper method to fetch the builder configs file.

    Downloads the builder configs file and returns it. This helper function
    allows the retry to target the gitiles download specifically.
    """
    # Step nesting needs to happen here or it shows up many times in Milo,
    # once for each builder.
    return self.m.gitiles.download_file(
        REPO_URL, "generated/builder_configs.binaryproto",
        branch=self._config_ref,
        step_test_data=self.test_api.builder_configs_step_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)

  def _get_name_to_builder_config(self, force_reload=False):
    """Helper method that returns the name to BuilderConfig map.

    Loads the proto and builds the map if it hasn't already been done.
    """
    if force_reload:
      self._name_to_builder_config.clear()
    if not self._name_to_builder_config:
      name_to_builder_config = {}
      # Step nesting needs to happen here or it shows up many times in Milo,
      # once for each builder.
      with self.m.step.nest('read builder configs'), self.m.context(
          infra_steps=True):
        builder_configs_file = self._fetch_builder_configs()
      configs = BuilderConfigs.FromString(builder_configs_file)
      for config in configs.builder_configs:
        name_to_builder_config[config.id.name] = config
      self._name_to_builder_config = name_to_builder_config
    return self._name_to_builder_config

  def get_builder_config(self, builder_name):
    """Gets the BuilderConfig for the specified builder from the master branch.

    Finds the BuilderConfig whose id.name matches the specified Buildbucket
    builder.

    This function loads the checked in proto and forms a map from id.name to
    BuilderConfig on the first call. Subsequent calls just look up in the map,
    so will be much faster than the first call. This is meant for the case when
    many lookups are needed, e.g. a parent builder looks up all child configs.

    Args:
      * builder_name (str): The Buildbucket builder to look for, matched against
        BuilderConfig's id.name.

    Returns:
      A BuilderConfigs proto.

    Raises:
      A LookupError if no BuilderConfig is found for the specified builder.
    """
    config = self._get_name_to_builder_config().get(builder_name)
    if not config:
      raise LookupError("No BuilderConfig for builder {}".format(builder_name))
    return config

  def safe_get_builder_configs(self, builder_names):
    """Gets the BuilderConfigs for the specified builder names from master.

    The returned dict will not contain key/values for builder names that could
    not be found in config.

    Args:
      * builder_names (list[str]): Buildbucket builders to look for, matched
        against BuilderConfig id.name.

    Returns:
      dict(str, BuilderConfig) of found BuilderConfigs.
    """
    builder_configs = {}
    for name in builder_names:
      try:
        builder_configs[name] = self.get_builder_config(name)
      except LookupError:
        # Carry on if the builder doesn't exist anymore.
        pass
    return builder_configs

  def force_reload(self):
    """Force a reload of the config map from ToT."""
    self._get_name_to_builder_config(force_reload=True)

  def should_run(self, run_spec):
    return run_spec in [BuilderConfig.RUN, BuilderConfig.RUN_EXIT]

  def should_exit(self, run_spec):
    return run_spec == BuilderConfig.RUN_EXIT

  def get_bot_policy_config(self):
    """Get BotPolicies as defined in infra/config.

    Returns:
      BotPolicyCfg as defined in the config repo.
    """
    bot_policy_file = self.m.gitiles.download_file(
        REPO_URL, "bot_scaling/generated/bot_policy.binaryproto",
        step_test_data=self.test_api.bot_policy_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)
    return BotPolicyCfg.FromString(bot_policy_file)

  def get_vm_retry_config(self):
    """Get SuiteRetryCfg as defined in infra/config for tast vm.

    Returns:
      SuiteRetryCfg as defined in the config repo.
    """
    vm_retry_config_file = self.m.gitiles.download_file(
        REPO_URL, "testingconfig/generated/vm_retry.binaryproto",
        step_test_data=self.test_api.vm_retry_test_data,
        timeout=self.test_api.gitiles_timeout_seconds)
    return SuiteRetryCfg.FromString(vm_retry_config_file)
