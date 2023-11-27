# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS TSE SuiteManager builder."""

from PB.recipes.chromeos.test_platform.suite_manager import SuiteManagerProperties

DEPS = [
    'recipe_engine/step',
]

PROPERTIES = SuiteManagerProperties


# TODO(b/284200039, b/284200038): Create a proto that will be used as the
# properties schema for the builder.
def RunSteps(api, properties):
  """Builder Entry Point

  Args:
    api: a RecipeScriptApi instance
    properties: default recipe properties

  Returns:
    None
  """
  with api.step.nest("Fetch Package") as presentation:
    presentation.logs["Fetching golang binary from CIP"] = 'Pass'

    # TODO(b/284200039, b/284200038): Fetch CIPD binary.


def GenTests(api):
  yield api.test("basic")
