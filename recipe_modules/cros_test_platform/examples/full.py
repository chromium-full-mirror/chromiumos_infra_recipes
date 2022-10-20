# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_test_platform.cros_test_platform import CrosTestPlatformModuleProperties
from PB.test_platform.steps.enumeration import EnumerationRequests
from PB.test_platform.steps.enumeration import EnumerationResponses
from PB.test_platform.steps.execution import ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponses

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
    api.cros_test_platform.execute_luciexe(None)

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
  with api.step.nest('callsite-execute-luciexe'):
    api.assertions.assertEqual(
        ExecuteResponses(),
        api.cros_test_platform.execute_luciexe(ExecuteRequests()),
    )


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
          'callsite-execute-luciexe', ExecuteResponses()),
  )
