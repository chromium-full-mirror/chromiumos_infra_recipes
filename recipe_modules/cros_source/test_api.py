# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosInfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_source module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60
