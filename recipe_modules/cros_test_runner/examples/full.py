# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_test_runner.cros_test_runner import CrosTestRunnerModuleProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_runner',
]



def RunSteps(api):
  api.assertions.assertEqual(api.cros_test_runner.cipd_package_label(),
                             'some-cipd-label')

  with api.step.nest('callsite-execute-luciexe'):
    api.cros_test_runner.is_dynamic()
    api.cros_test_runner.is_enabled()
    api.cros_test_runner.execute_luciexe()
    api.cros_test_runner.ensure_cros_test_runner()


def GenTests(api):
  yield api.test(
      'custom-label',
      api.properties(
          **{
              '$chromeos/cros_test_runner':
                  CrosTestRunnerModuleProperties(
                      version=CrosTestRunnerModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }) +  #
      api.cros_test_runner.mock_luciexe_call('callsite-execute-luciexe'),
  )
