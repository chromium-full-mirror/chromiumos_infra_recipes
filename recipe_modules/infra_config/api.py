# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from google.protobuf import json_format as jsonpb

from PB.chromiumos.builder_config import BuilderConfigs

REPO_URL = "https://chrome-internal.googlesource.com/chromeos/infra/config"


class InfraConfigApi(recipe_api.RecipeApi):
  """A module for accessing data in the chromeos/infra/config repo"""

  def initialize(self):
    """Init the InfraConfigApi module."""
    # Map from BuilderConfig's id.name to BuilderConfig, lazily loaded.
    self._name_to_builder_config = {}

  def _get_name_to_builder_config(self):
    """Helper method that returns the name to BuilderConfig map.

    Loads the proto and builds the map if it hasn't already been done.
    """
    if not self._name_to_builder_config:
      builder_configs_file = self.m.gitiles.download_file(
          REPO_URL, "generated/builder_configs.cfg",
          step_test_data=self.test_api.builder_configs_step_test_data)
      # Ignore unknown fields, as this repo may not be using the newest version
      # of the proto.
      builder_configs = jsonpb.Parse(builder_configs_file, BuilderConfigs(),
                                     ignore_unknown_fields=True).builder_configs
      for config in builder_configs:
        self._name_to_builder_config[config.id.name] = config

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
    with self.m.context(infra_steps=True):
      config = self._get_name_to_builder_config().get(builder_name)
      if not config:
        raise LookupError(
            "No BuilderConfig for builder {}".format(builder_name))

      return config

  def get_test_config(self, config_name):
    """Gets Path of most recent test config.

    Args:
      * config_name (str): Config filename.

    Returns:
      Path pointing to specified config file.
    """
    conf_contents = self.m.gitiles.download_file(
        REPO_URL, "testingconfig/generated/%s" % config_name,
        step_test_data=self.test_api.test_config_file)

    path = self.m.path['cleanup'].join('testconfig', config_name, conf_contents)

    self.m.file.write_raw('save %s' % config_name, path, conf_contents)
    return path
