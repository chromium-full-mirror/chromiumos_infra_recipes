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
      "Tree":"ahFzfnNoZXJpZmYtby1tYXRpY3ISCxIEVHJlZSIIY2hyb21lb3MM",
      "KeyDigest":"1193804a7ba70acd455282bf518ee8136291f319",
      "key":"chromeos.buildbucket:create sysroot|call chromite.api.SysrootService/Create|call build API script",
      "bugs":null,
      "comments":null,
      "snoozeTime":0,
      "group_id":"b5da2ccf-ac62-446e-84bb-0b01b2a74317",
      "ModificationTime":"2019-06-14T22:15:09.958855Z",
      "bug_data":{

      }
   },
   {
      "Tree":"ahFzfnNoZXJpZmYtby1tYXRpY3ISCxIEVHJlZSIIY2hyb21lb3MM",
      "KeyDigest":"11d6361922cd503e390b82be665b8d82bdd385b8",
      "key":"chromeos.buildbucket:ensure manifest cq-depend fulfilled|git log (3)",
      "bugs":[
         "974630"
      ],
      "comments":null,
      "snoozeTime":1560838289688,
      "group_id":"",
      "ModificationTime":"2019-06-18T05:11:29.784021Z",
      "bug_data":{
         "974630":{
            "author":{
               "name":"jclinton@chromium.org"
            },
            "cc":[
               {
                  "name":"evanhernandez@google.com"
               },
               {
                  "name":"andrewlamb@chromium.org"
               },
               {
                  "name":"nednguyen@google.com"
               },
               {
                  "name":"dats@chromium.org"
               },
               {
                  "name":"seanabraham@chromium.org"
               },
               {
                  "name":"acourbot@google.com"
               },
               {
                  "name":"sammc@chromium.org"
               }
            ],
            "id":974630,
            "components":[
               "Infra\u003eChromeOS\u003eCI",
               "OS\u003ePackages"
            ],
            "labels":[
               "Type-Bug",
               "Pri-0",
               "OS-Chrome"
            ],
            "owner":{
               "name":"jclinton@chromium.org"
            },
            "status":"Fixed",
            "summary":"Annealing broken by repo moving between branches in manifest-internal",
            "updated":"2019-06-18T16:04:40",
            "projectId":"chromium"
         }
      }
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
