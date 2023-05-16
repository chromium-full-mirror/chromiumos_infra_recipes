# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Compile and sync proto files across ChromeOS.

This recipe should normally be triggered via a gitiles_poller that watches for
changes to the infra/proto repo. The poller should batch requests, so there may
be several changes, which may be on different branches.
For more info on gitiles_pollers, see go/lucicfg#luci.gitiles_poller.
"""

from typing import Generator

from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = []


def RunSteps(api: recipe_api.RecipeApi) -> None:
  """Main recipe logic.

  In a nutshell, for each branch in this build's triggers:
  1.  Compile Chromite proto bindings, and submit them to Gerrit.
  2.  Sync proto bindings to prebuilts-cloud project, and submit them to Gerrit.

  Of course, each step is more nuanced than that. See function-specific
  docstrings.
  """
  del api


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test('basic')
