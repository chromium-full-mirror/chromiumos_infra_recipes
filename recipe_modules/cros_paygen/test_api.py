# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""

from recipe_engine import recipe_test_api


class PaygenTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing Chrome OS Paygen Recipes."""

  EXAMPLE_PAYGEN_JSON = """
  {
    "delta": [
        {
          "board": {
            "public_codename": "amenia",
            "is_active": false,
            "builder_name": "amenia"
          },
          "delta_type": "NO_DELTA",
          "generate_delta": false,
          "delta_payload_tests": false,
          "full_payload_tests": false
        },
        {
          "board": {
            "public_codename": "arkham",
            "is_active": true,
            "builder_name": "arkham"
          },
          "delta_type": "NO_DELTA",
          "generate_delta": false,
          "delta_payload_tests": false,
          "full_payload_tests": false
        },
        {
          "board": {
            "public_codename": "octopus",
            "is_active": true,
            "builder_name": "octopus"
          },
          "delta_type": "OMAHA",
          "channel": "dev",
          "chrome_os_version": "13310.24.0",
          "chrome_version": "85.0.4183.34",
          "milestone": 85,
          "generate_delta": true,
          "delta_payload_tests": true,
          "full_payload_tests": true,
          "applicable_models": [
            "garfour"
          ]
        }
    ]
  }
  """
  EXAMPLE_EMPTY_JSON = "{}"
  EXAMPLE_NOT_EVEN_JSON = "dawiojdoiawjdioawjdow"
  ALL_EXAMPLE_JSONS = [
      EXAMPLE_PAYGEN_JSON, EXAMPLE_EMPTY_JSON, EXAMPLE_NOT_EVEN_JSON
  ]

  def mock_paygen(self, step_name, json_return):
    """Mock up step results for the GS cat."""
    mock_response = self.m.step.step_data(
        step_name, stdout=self.m.raw_io.output(json_return))
    return mock_response
