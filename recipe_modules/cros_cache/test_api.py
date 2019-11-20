# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosCacheTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_cache module."""

  # Number of seconds to wait on gsutil rsync.
  gsutil_timeout_seconds = 15 * 60
