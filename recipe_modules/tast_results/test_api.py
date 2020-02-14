# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_test_api


class TastResultsTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the tast_results module."""

  gsutil_timeout_seconds = 120
  test_results_json = json.loads("""
[
  {
    "name": "arc.Boot",
    "pkg": "chromiumos/tast/local/bundles/cros/arc",
    "additionalTime": 30000000000,
    "desc": "Checks that Android boots",
    "contacts": [
      "ereth@chromium.org",
      "arc-core@google.com",
      "nya@chromium.org"
    ],
    "attr": [
      "name:arc.Boot",
      "bundle:cros",
      "dep:chrome",
      "dep:android_all",
      "group:mainline"
    ],
    "data": null,
    "softwareDeps": [
      "chrome",
      "android_all"
    ],
    "timeout": 300000000000,
    "errors": [
      {
        "reason": "Lost SSH connection to VM"
      }
    ],
    "start": "2020-01-27T15:16:15.146771555-08:00",
    "end": "2020-01-27T15:16:33.420622341-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/arc.Boot",
    "skipReason": ""
  },
  {
    "name": "arc.BuildProperties",
    "pkg": "chromiumos/tast/local/bundles/cros/arc",
    "additionalTime": 30000000000,
    "desc": "Checks important Android properties such as first_api_level",
    "contacts": [
      "niwa@chromium.org",
      "risan@chromium.org",
      "arc-eng@google.com"
    ],
    "attr": [
      "name:arc.BuildProperties",
      "bundle:cros",
      "dep:android",
      "dep:chrome",
      "group:mainline"
    ],
    "data": null,
    "softwareDeps": [
      "android",
      "chrome"
    ],
    "timeout": 240000000000,
    "errors": null,
    "start": "2020-01-27T15:16:33.421007899-08:00",
    "end": "2020-01-27T15:16:36.833644627-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/arc.BuildProperties",
    "skipReason": ""
  },
  {
    "name": "arc.MiniContainerState",
    "pkg": "chromiumos/tast/local/bundles/cros/arc",
    "additionalTime": 30000000000,
    "desc": "Verifies ARC mini container starts right after Chrome OS shows the login screen",
    "contacts": [
      "yusukes@chromium.org",
      "arc-core@google.com",
      "hidehiko@chromium.org"
    ],
    "attr": [
      "name:arc.MiniContainerState",
      "bundle:cros",
      "dep:android",
      "dep:chrome",
      "group:mainline"
    ],
    "data": null,
    "softwareDeps": [
      "android",
      "chrome"
    ],
    "timeout": 240000000000,
    "errors": null,
    "start": "2020-01-27T15:16:36.833776957-08:00",
    "end": "2020-01-27T15:16:40.090886944-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/arc.MiniContainerState",
    "skipReason": ""
  }
]
""")
