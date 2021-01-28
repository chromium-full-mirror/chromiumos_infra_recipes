# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_runner',
]

from PB.recipe_modules.chromeos.cros_test_runner.cros_test_runner import \
  CrosTestRunnerModuleProperties
from PB.test_platform.skylab_test_runner.steps.test_execution import RunTestsRequest, RunTestsResponse


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.cros_test_runner.execute_luciexe(None)

  api.assertions.assertEqual(api.cros_test_runner.cipd_package_version(),
                             'some-cipd-label')

  with api.step.nest('callsite-execute-luciexe'):
    api.assertions.assertEqual(
        RunTestsResponse(),
        api.cros_test_runner.execute_luciexe(RunTestsRequest()),
    )


def GenTests(api):
  yield api.test(
      'custom_label',
      api.properties(
          **{
              '$chromeos/cros_test_runner':
                  CrosTestRunnerModuleProperties(
                      version=CrosTestRunnerModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }) +  #
      api.cros_test_runner.set_execute_luciexe_response(
          'callsite-execute-luciexe', RunTestsResponse()),
  )
