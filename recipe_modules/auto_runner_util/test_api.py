# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module with helper functions for testing auto_runner_util."""

import json
import os
from recipe_engine import recipe_test_api


class AutoRunnerUtilTestApi(recipe_test_api.RecipeTestApi):
  """Test API for auto_runner_util."""

  def get_test_output_as_jsonobj(self, filename: str) -> str:
    with open(
        os.path.join(os.path.abspath(os.path.dirname(__file__)), filename),
        encoding='utf-8') as f:
      return json.load(f)
