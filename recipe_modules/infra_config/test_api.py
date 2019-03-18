# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class InfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the infra_config module."""

  def builder_configs_step_test_data(self):
    """A fn that can be passed to step_test_data to generate BuilderConfigs.

    Note the field "newUnknownField", which tests the case where the proto in
    chromeos/infra/config is using a proto version newer than the one in this
    repo.
    """
    return self.m.gitiles.make_encoded_file("""
            {
              "builderConfigs": [
                {
                  "id": {
                    "name": "amd64-generic-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT",
                    "newUnknownField": "some-value"
                  },
                  "general": {
                    "critical": true
                  }
                },
                {
                  "id": {
                    "name": "postsubmit-orchestrator",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": true
                  },
                  "orchestrator": {
                    "children": [
                      "amd64-generic-postsubmit",
                      "arm-generic-postsubmit"
                    ]
                  }
                }
              ]
            }
          """)
