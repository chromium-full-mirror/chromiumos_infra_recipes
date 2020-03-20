# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.gce.api.config.v1.config import Config, Configs


class BotScalingTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  def previous_robocrop(self):
    """Generate a struct for the 'build_target_test_status' property.

    Returns:
      Build: Containing the expected output properties.
    """
    build = build_pb2.Build(id=123,
                            builder=build_pb2.BuilderID(builder='RoboCrop'),
                            status=common_pb2.SUCCESS)
    build.output.properties.update({
        'robocrop_action': self.robocrop_action_dict()
    })
    return build

  def robocrop_action_dict(self):
    return {
        "scalingActions": [{
            "botType": {
                "coresPerBot": 32,
                "botSize": "large"
            },
            "botsRequested":
                1500,
            "botGroup":
                "cq",
            "regionalActions": [
                {
                    "prefix": "chromeos-ci-cq-us-central1-b-x32",
                    "region": "us-central1-b",
                    "botsRequested": 367
                },
                {
                    "prefix": "chromeos-ci-cq-us-central2-d-x32",
                    "region": "us-central2-d",
                    "botsRequested": 464
                },
                {
                    "region": "us-east1-d",
                    "prefix": "chromeos-ci-cq-us-east1-d-x32",
                    "botsRequested": 367
                },
                {
                    "prefix": "chromeos-ci-cq-us-west1-b-x32",
                    "region": "us-west1-b",
                    "botsRequested": 300
                }
            ]
        }]
    }

  def gce_provider_stats(self):
    return Configs(vms=[
        Config(prefix='prefix-first', current_amount=35),
        Config(prefix='prefix-second', current_amount=35)
    ])
