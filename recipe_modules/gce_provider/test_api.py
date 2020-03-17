# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GceProviderTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the GCE Provider module."""

  def get_current_config_step_test_data(self):
    """Returns a dict of current config.

    Returns:
      config(dict): Dictionary of GCE Provider config
    """
    return {
        "amount": {
            "max": 15,
            "min": 15
        },
        "attributes": {
            "disk": [{
                "image": "global/images/chromeos-bionic-20031500-6b26172a85c",
                "size": "750"
            }],
            "machineType":
                "zones/{{.Zone}}/machineTypes/custom-32-65536",
            "metadata": [{
                "fromText": ""
            }],
            "minCpuPlatform":
                "Intel Broadwell",
            "networkInterface": [{
                "network": "global/networks/machine-provider-bot-network"
            }],
            "project":
                "chromeos-bot",
            "serviceAccount": [{
                "email":
                    "test-email@developer.gserviceaccount.com",
                "scope": [
                    "https://www.googleapis.com/auth/devstorage.full_control",
                    "https://www.googleapis.com/auth/gerritcodereview",
                    "https://www.googleapis.com/auth/logging.write",
                    "https://www.googleapis.com/auth/monitoring",
                    "https://www.googleapis.com/auth/pubsub",
                    "https://www.googleapis.com/auth/userinfo.email"
                ]
            }],
            "zone":
                "us-central1-b"
        },
        "currentAmount": 15,
        "lifetime": {
            "seconds": "86400"
        },
        "prefix": "chromeos-ci-cq-us-central1-b-x32",
        "revision": "4414d646bb94ed7b9129aa980bdf0794cc5ebc59",
        "swarming": "https://chromeos-swarming.appspot.com"
    }
