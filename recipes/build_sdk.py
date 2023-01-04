# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

from PB.chromite.api.sdk import BuildPrebuiltsRequest
from PB.recipes.chromeos.build_sdk import BuildSDKProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildSDKProperties


def RunSteps(api: RecipeApi, properties: BuildSDKProperties):
  BuildSDKRun(api, properties).run()


class BuildSDKRun:
  """Class to encapsulate a single run of the SDK builder."""

  def __init__(self, api: RecipeApi, properties: BuildSDKProperties):
    """Initialize the builder run."""
    self.m = api
    self.properties = properties

  def run(self):
    """Run the main logic for this builder."""
    with self.m.build_menu.configure_builder(missing_ok=True), \
        self.m.build_menu.setup_workspace_and_chroot(bootstrap_chroot=True, replace=True):
      self._build_sdk_packages()

  def _build_sdk_packages(self):
    """Build all packages for the SDK build target."""
    request = BuildPrebuiltsRequest(chroot=self.m.cros_sdk.chroot)
    self.m.cros_build_api.SdkService.BuildPrebuilts(request)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic', api.properties(build_target={'name': 'amd64-host'}),
      api.post_check(post_process.MustRun,
                     'call chromite.api.SdkService/BuildPrebuilts'),
      api.post_check(post_process.StatusSuccess))
