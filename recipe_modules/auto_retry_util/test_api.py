# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module with utility function for testing auto_retry_util."""

from recipe_engine import recipe_test_api
from recipe_engine.recipe_test_api import TestData


class AutoRetryUtilTestApi(recipe_test_api.RecipeTestApi):

  def enable_retries(self) -> TestData:
    """Returns properties for the auto_retry_util module to enable retries"""
    return self.m.properties(
        **{'$chromeos/auto_retry_util': {
            'enable_retries': True
        }})
