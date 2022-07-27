# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class ExonerateTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing Exonerate module."""

  def fake_exoneration_configs(self):
    """Returns fake configs for unittesting."""
    return {
        "test1": [{
            "targets": ["eve"],
        }],
        "test2": [{
            "targets": [],
        }],
        "arc.Boot": [{
            "targets": ["betty"],
        }],
        "test3": [{
            "targets": ["build_target_name"],
        }]
    }
