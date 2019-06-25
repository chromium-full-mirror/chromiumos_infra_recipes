# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

import json


class CrosSomTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_som module."""

  @property
  def test_annotation_response(self):
    return json.loads("""
[
   {
      "key":"chromeos.buildbucket:hw test results (3)|[FAILED] target.hw.bvt-cq",
      "bugs":[
        "1234"
      ],
      "snoozeTime": 0
   },
   {
      "key":"chromeos.buildbucket:vm test results (3)|[FAILED] target.vm.suite",
      "bugs":null,
      "snoozeTime": 9999000000000
   },
   {
      "key":"chromeos.buildbucket:vm test results (3)|[FAILED] target.vm.suite (2)",
      "bugs":null,
      "snoozeTime": 0
   },
   {
      "key":"chromeos.buildbucket:build results (4)|[FAILED] ..",
      "bugs":[
        "780"
      ],
      "snoozeTime": 0
   },
   {
      "key":"123",
      "group_id":"Hardware lab network outage"
   }
]
    """)
