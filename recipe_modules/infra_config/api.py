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

  def get_current_builder_config(self):
    """Gets the BuilderConfig for the current builder from the master branch.

    Finds the BuilderConfig whose id.name matches the current Buildbucket
    builder.

    Returns:
      A BuilderConfigs proto.

    Raises:
      A ValueError if no BuilderConfig is found for the current builder.
    """
    builder_configs_file = self.m.gitiles.download_file(
        REPO_URL, "generated/builder_configs.cfg",
        step_test_data=self.test_api.builder_configs_step_test_data)
    # Ignore unknown fields, as this repo may not be using the newest version
    # of the proto.
    builder_configs = jsonpb.Parse(builder_configs_file, BuilderConfigs(),
                                   ignore_unknown_fields=True).builder_configs

    current_builder_name = self.m.buildbucket.build.builder.builder
    for config in builder_configs:
      if config.id.name == current_builder_name:
        return config

    raise LookupError(
        "No BuilderConfig for builder {}".format(current_builder_name))
