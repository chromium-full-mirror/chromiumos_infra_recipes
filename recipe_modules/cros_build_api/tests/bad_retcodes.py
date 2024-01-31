# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import artifacts
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_build_api.cros_build_api import CrosBuildApiProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
]



def RunSteps(api):
  input_proto = artifacts.BundleRequest(build_target=BuildTarget(name='target'))
  api.assertions.assertRaises(
      api.step.StepFailure, api.cros_build_api.ArtifactsService.BundleFirmware,
      input_proto)


def GenTests(api):
  # 1 and 3 are the two codes defined explicitly as failure codes for the
  # structured return codes of the build API. Of course any other than
  # the defined response available codes 0 and 2 would also raise a
  # StepFailure.

  # Build API unrecoverable.
  yield api.test(
      'retcode-one-bad',
      api.properties(
          **{
              '$chromeos/cros_build_api':
                  CrosBuildApiProperties(capture_stdout_stderr=True)
          }),
      api.step_data(
          'call chromite.api.ArtifactsService/'
          'BundleFirmware.call build API script', retcode=1))

  # Build API completed unsuccessfully.
  yield api.test(
      'retcode-three-bad',
      api.step_data(
          'call chromite.api.ArtifactsService/'
          'BundleFirmware.call build API script', retcode=3))
