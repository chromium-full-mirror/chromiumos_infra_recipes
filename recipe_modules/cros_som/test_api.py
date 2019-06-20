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
   }
]
    """)

  def get_malformed_key_step_data(self):
    """Get step data for the case when a "key" field is invalid."""
    return self.m.url.json(
        'Get Sheriff-o-Matic annotations',
        json.loads("""
[
   {
      "Tree":"ahFzfnNoZXJpZmYtby1tYXRpY3ISCxIEVHJlZSIIY2hyb21lb3MM",
      "KeyDigest":"1193804a7ba70acd455282bf518ee8136291f319",
      "key":"invalid_prefix:create sysroot|call chromite.api.SysrootService/Create|call build API script",
      "bugs":null,
      "comments":null,
      "snoozeTime":0,
      "group_id":"b5da2ccf-ac62-446e-84bb-0b01b2a74317",
      "ModificationTime":"2019-06-14T22:15:09.958855Z",
      "bug_data":{

      }
   }
]
    """))
