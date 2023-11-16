# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_test_platform.cros_test_platform import CrosTestPlatformModuleProperties
from PB.test_platform.steps.enumeration import EnumerationRequests
from PB.test_platform.steps.enumeration import EnumerationResponses
from PB.test_platform.steps.execution import ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponses

from PB.recipes.chromeos.test_platform.cros_test_platform import CrosTestPlatformProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_platform',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.enumerate(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.skylab_execute(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.execute_luciexe(CrosTestPlatformProperties(), None)

  api.assertions.assertEqual(api.cros_test_platform.cipd_package_version(),
                             'some-cipd-label')

  with api.step.nest('callsite-enumerate'):
    api.assertions.assertEqual(
        EnumerationResponses(),
        api.cros_test_platform.enumerate(EnumerationRequests()),
    )
  with api.step.nest('callsite-skylab-execute'):
    api.assertions.assertEqual(
        ExecuteResponses(),
        api.cros_test_platform.skylab_execute(ExecuteRequests()),
    )
  with api.step.nest('callsite-execute-luciexe-no-suite-limit'):
    response, _ = api.cros_test_platform.execute_luciexe(
        CrosTestPlatformProperties(), ExecuteRequests())
    api.assertions.assertEqual(ExecuteResponses(), response)

  with api.step.nest('callsite-execute-luciexe-with-suite-limit'):
    response, _ = api.cros_test_platform.execute_luciexe(
        CrosTestPlatformProperties(
            experiments=[CrosTestPlatformProperties.SUITE_EXECUTION_LIMIT]),
        ExecuteRequests())
    api.assertions.assertEqual(ExecuteResponses(), response)

  with api.step.nest('callsite-execute-luciexe-optimized-sharding'):
    response, _ = api.cros_test_platform.execute_luciexe(
        CrosTestPlatformProperties(
            experiments=[CrosTestPlatformProperties.OPTIMIZED_SHARDING]),
        ExecuteRequests())
    api.assertions.assertEqual(ExecuteResponses(), response)


def GenTests(api):
  yield api.test(
      'custom-label',
      api.properties(
          **{
              '$chromeos/cros_test_platform':
                  CrosTestPlatformModuleProperties(
                      version=CrosTestPlatformModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }) +  #
      api.cros_test_platform.set_enumerate_response_json(
          'callsite-enumerate', '{}') +  #
      api.cros_test_platform.set_skylab_execute_response(
          'callsite-skylab-execute', ExecuteResponses()),
      api.cros_test_platform.set_execute_luciexe_response(
          'callsite-execute-luciexe-no-suite-limit', ExecuteResponses()),
      api.cros_test_platform.set_execute_luciexe_response(
          'callsite-execute-luciexe-with-suite-limit', ExecuteResponses()),
      api.cros_test_platform.set_execute_luciexe_response(
          'callsite-execute-luciexe-optimized-sharding', ExecuteResponses()),
  )
