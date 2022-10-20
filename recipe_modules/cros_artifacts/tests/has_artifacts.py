# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.common import ArtifactsByService

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  Legacy = ArtifactsByService.Legacy
  Toolchain = ArtifactsByService.Toolchain

  # Legacy output artifacts work.
  api.assertions.assertTrue(
      api.cros_artifacts.has_output_artifacts(
          ArtifactsByService(
              legacy=Legacy(output_artifacts=[
                  Legacy.ArtifactInfo(artifact_types=['EBUILD_LOGS'])
              ]))))

  # Toolchain output artifacts work.
  api.assertions.assertTrue(
      api.cros_artifacts.has_output_artifacts(
          ArtifactsByService(
              toolchain=Toolchain(output_artifacts=[
                  Toolchain.ArtifactInfo(artifact_types=['CHROME_DEBUG_BINARY'])
              ]))))

  # Input artifacts are not output artifacts.
  api.assertions.assertFalse(
      api.cros_artifacts.has_output_artifacts(
          ArtifactsByService(
              legacy=Legacy(input_artifacts=[
                  Legacy.ArtifactInfo(artifact_types=['EBUILD_LOGS'])
              ]))))


def GenTests(api):
  yield api.test('basic')
