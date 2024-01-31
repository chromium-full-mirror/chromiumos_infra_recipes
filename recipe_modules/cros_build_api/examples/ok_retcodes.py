# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import artifacts
from PB.chromiumos.common import BuildTarget

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_build_api',
]



def RunSteps(api):
  input_proto = artifacts.BundleRequest(build_target=BuildTarget(name='target'))
  output_proto = api.cros_build_api.ArtifactsService.BundleFirmware(
      input_proto, step_text='text')

  # Got here and did not raise.
  api.assertions.assertTrue(
      output_proto.artifacts[0].path.endswith('/tmp/artifact.tar.gz'))


def GenTests(api):
  # 0 and 2 are defined as the two codes where a consumable response is
  # available per the structured return codes of the build API. All other
  # codes would raise a StepFailure.

  # Build API success / ordinary success.
  yield api.test(
      'retcode-zero-ok',
      api.step_data(
          'call chromite.api.ArtifactsService/'
          'BundleFirmware.call build API script', retcode=0))

  # Build API unsuccessful but response available.
  yield api.test(
      'retcode-two-ok',
      api.step_data(
          'call chromite.api.ArtifactsService/'
          'BundleFirmware.call build API script', retcode=2))
