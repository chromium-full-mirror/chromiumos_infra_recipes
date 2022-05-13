# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
]

from PB.chromiumos.common import ArtifactsByService

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


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
