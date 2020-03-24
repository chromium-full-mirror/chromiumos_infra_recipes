# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class ChromeTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the chrome module."""

  # Number of seconds to wait on gclient sync.
  gclient_sync_timeout_seconds = int(1.5 * 60 * 60)

  # Number of seconds to wait to retry gclient sync.
  gclient_sync_sleep_seconds = 2 * 60

  # Max number of times to try gclient.
  gclient_sync_max_retries = 2
