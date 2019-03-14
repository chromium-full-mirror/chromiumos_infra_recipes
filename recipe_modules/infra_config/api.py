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

  def get_builder_configs(self):
    """Gets BuilderConfigs from the master branch.

    Returns:
      A BuilderConfigs proto.
    """
    builder_configs_file = self.m.gitiles.download_file(
        REPO_URL, "generated/builder_configs.cfg",
        step_test_data=self.test_api.builder_configs_step_test_data)
    # Ignore unknown fields, as this repo may not be using the newest version
    # of the proto.
    return jsonpb.Parse(builder_configs_file, BuilderConfigs(),
                        ignore_unknown_fields=True)
