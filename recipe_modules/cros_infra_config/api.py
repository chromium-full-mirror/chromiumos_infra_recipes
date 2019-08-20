# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from google.protobuf import json_format as jsonpb
from util import exponential_retry

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.builder_config import BuilderConfigs

REPO_URL = "https://chrome-internal.googlesource.com/chromeos/infra/config"


class CrosInfraConfigApi(recipe_api.RecipeApi):
  """A module for accessing data in the chromeos/infra/config repo"""

  def initialize(self):
    """Init the InfraConfigApi module."""
    # Map from BuilderConfig's id.name to BuilderConfig, lazily loaded.
    self._name_to_builder_config = {}

  @exponential_retry(retries=3, condition=lambda e: e.had_timeout)
  def _fetch_builder_configs(self):
    """Helper method to fetch the builder configs file.

    Downloads the builder configs file and returns it. This helper function
    allows the retry to target the gitiles download specifically.
    """
    # Step nesting needs to happen here or it shows up many times in Milo,
    # once for each builder.
    return self.m.gitiles.download_file(
        REPO_URL, "generated/builder_configs.cfg",
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
      with self.m.step.nest('read build config'), self.m.context(
          infra_steps=True):
        builder_configs_file = self._fetch_builder_configs()
      # Ignore unknown fields, as this repo may not be using the newest version
      # of the proto.
      builder_configs = jsonpb.Parse(builder_configs_file, BuilderConfigs(),
                                     ignore_unknown_fields=True).builder_configs
      for config in builder_configs:
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

  def get_test_config(self, config_name):
    """Gets Path of most recent test config.

    Args:
      * config_name (str): Config filename.

    Returns:
      Path pointing to specified config file.
    """
    with self.m.step.nest('read test config'), self.m.context(infra_steps=True):
      conf_contents = self.m.gitiles.download_file(
          REPO_URL, "testingconfig/generated/%s" % config_name,
          step_test_data=self.test_api.test_config_file)

      outdir = self.m.path['cleanup'].join('testconfig')
      self.m.file.ensure_directory('make testconfig', outdir)
      path = outdir.join(config_name)

      self.m.file.write_raw('save %s' % config_name, path, conf_contents)
      return path

  def force_reload(self):
    """Force a reload of the config map from ToT."""
    self._get_name_to_builder_config(force_reload=True)

  def should_run(self, run_spec):
    return run_spec in [BuilderConfig.RUN, BuilderConfig.RUN_EXIT]

  def should_exit(self, run_spec):
    return run_spec == BuilderConfig.RUN_EXIT
