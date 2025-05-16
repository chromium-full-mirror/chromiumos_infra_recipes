# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Shows the usage of set_toolchain_service_artifacts_result."""

from recipe_engine import post_process

from PB.chromite.api import toolchain

DEPS = [
    'recipe_engine/step',
    'cros_build_api',
]


def RunSteps(api):
  with api.step.nest('test step'):
    api.cros_build_api.ToolchainService.BundleArtifacts(
        toolchain.BundleToolchainRequest())


def GenTests(api):
  yield api.test(
      'basic',
      api.cros_build_api.set_toolchain_service_artifacts_result(
          {'BundleArtifacts': '{"foo": "bar"}'}),
      api.post_check(
          post_process.StepSuccess,
          'test step.call chromite.api.ToolchainService/BundleArtifacts',
      ), api.post_process(post_process.DropExpectation))
