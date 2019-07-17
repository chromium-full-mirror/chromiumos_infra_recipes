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
      "key":"chromeos.buildbucket:step with linked bugs",
      "bugs":[
        "1234"
      ],
      "snoozeTime": 0,
      "group_id":""
   },
   {
      "key":"chromeos.buildbucket:snoozed step",
      "bugs":null,
      "snoozeTime": 9999000000000,
      "group_id":""
   },
   {
      "key":"chromeos.buildbucket:step with no snoozes or linked bugs",
      "bugs":null,
      "snoozeTime": 0,
      "group_id":""
   },
   {
      "key":"chromeos.buildbucket:build results (4)|chromeos.bucket.builder",
      "bugs":null,
      "snoozeTime": 9999000000000,
      "group_id":""
   },
   {
      "key":"chromeos.buildbucket:build results (5)|chromeos.bucket.builder",
      "bugs":null,
      "snoozeTime": 9999000000000,
      "group_id":""
   },
   {
      "key":"123",
      "snoozeTime": 9999000000000,
      "group_id":"Group with snooze",
      "bugs":null
   },
   {
      "key":"chromeos.buildbucket:step in group with snooze",
      "bugs":null,
      "snoozeTime": 0,
      "group_id":"123"
   }
]
    """)
