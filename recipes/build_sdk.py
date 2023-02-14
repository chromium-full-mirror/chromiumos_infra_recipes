# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

from typing import List

from PB.chromite.api.sdk import BuildPrebuiltsRequest
from PB.chromite.api.sdk import BuildSdkTarballRequest
from PB.chromite.api.sdk import BuildSdkToolchainRequest
from PB.chromite.api.sdk import CreateManifestFromSdkRequest
from PB.chromiumos import common as common_pb2
from PB.recipes.chromeos.build_sdk import BuildSDKProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildSDKProperties

# LLVM_NEXT_USE_FLAG is the name of the USE flag for llvm-next builds.
LLVM_NEXT_USE_FLAG = 'llvm-next'


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
      self._build_toolchain()
      self._create_sdk_tarball()
      self._create_sdk_manifest()

  def _build_sdk_packages(self):
    """Build all packages for the SDK build target."""
    request = BuildPrebuiltsRequest(chroot=self.m.cros_sdk.chroot)
    self.m.cros_build_api.SdkService.BuildPrebuilts(request)

  def _build_toolchain(self) -> List[common_pb2.Path]:
    """Build cross-compiling toolchains for the SDK."""
    request = BuildSdkToolchainRequest(chroot=self.m.cros_sdk.chroot)
    if self.properties.use_llvm_next:
      request.use_flags.add(flag=LLVM_NEXT_USE_FLAG)
    response = self.m.cros_build_api.SdkService.BuildSdkToolchain(request)
    return response.generated_files

  def _create_sdk_tarball(self) -> common_pb2.Path:
    """Create a tarball containing a previously built SDK.

    Returns:
      Path to the newly created tarball.
    """
    request = BuildSdkTarballRequest(chroot=self.m.cros_sdk.chroot)
    response = self.m.cros_build_api.SdkService.BuildSdkTarball(request)
    return response.sdk_tarball_path

  def _create_sdk_manifest(self) -> common_pb2.Path:
    """Create a manifest file showing the ebuilds in an SDK.

    Returns:
      Path to the newly created manifest.
    """
    request = CreateManifestFromSdkRequest(
        chroot=self.m.cros_sdk.chroot,
        sdk_path=common_pb2.Path(
            path="build/amd64-host",
            location=common_pb2.Path.INSIDE,
        ),
        dest_dir=common_pb2.Path(
            path=str(self.m.workspace_util.workspace_path),
            location=common_pb2.Path.OUTSIDE,
        ),
    )
    response = self.m.cros_build_api.SdkService.CreateManifestFromSdk(request)
    return response.manifest_path


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic', api.properties(build_target={'name': 'amd64-host'}),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildPrebuilts'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkToolchain'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkTarball'),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/CreateManifestFromSdk'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'llvm-next',
      api.properties(build_target={'name': 'amd64-host'}, use_llvm_next=True),
      api.post_check(post_process.StepSuccess,
                     'call chromite.api.SdkService/BuildSdkToolchain'),
      api.post_check(post_process.LogContains,
                     'call chromite.api.SdkService/BuildSdkToolchain',
                     'request', [f'"flag": "{LLVM_NEXT_USE_FLAG}"']),
      api.post_process(post_process.DropExpectation),
  )
