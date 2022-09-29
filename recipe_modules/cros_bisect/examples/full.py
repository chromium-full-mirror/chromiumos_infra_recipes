# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.common import PackageInfo
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import CrosBisectProperties
from PB.recipe_modules.chromeos.cros_bisect.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_bisect',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.cros_bisect.set_bisect_builder('wally')
  api.cros_bisect.set_orchestrator_bisect_builder()
  api.assertions.assertCountEqual(api.cros_bisect.get_packages(),
                                  properties.expected_packages)

  api.assertions.assertEqual(api.cros_bisect.get_test_child_builders(),
                             properties.expected_test_child_builders)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'findit-compilation-failures-rerun-build',
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  CrosBisectProperties(
                      compile={
                          'targets': [
                              api.cros_bisect.serialized_package_info(
                                  'foo', 'cat1', '1'),
                              api.cros_bisect.serialized_package_info(
                                  'bar', 'cat1', '2'),
                              api.cros_bisect.serialized_package_info(
                                  'baz', 'cat2', '3'),
                          ]
                      })
          }),
      api.properties(
          TestInputProperties(expected_packages=[
              PackageInfo(package_name='foo', category='cat1', version='1'),
              PackageInfo(package_name='bar', category='cat1', version='2'),
              PackageInfo(package_name='baz', category='cat2', version='3'),
          ])),
  )

  yield api.test(
      'failed-build-with-bisection-enabled',
      api.properties(
          TestInputProperties(failed_packages=[
              PackageInfo(package_name='uno', category='pkg', version='1'),
              PackageInfo(package_name='dos', category='pkg', version='2'),
          ])),
  )

  hw_test_unit1 = api.cros_bisect.serialized_hw_test_unit('foo')
  hw_test_unit2 = api.cros_bisect.serialized_hw_test_unit('bar')
  hw_test_unit3 = api.cros_bisect.serialized_hw_test_unit('bar')

  yield api.test(
      'findit-test-failures-rerun-build',
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  CrosBisectProperties(
                      test={
                          'hw_test_failures': [
                              CrosBisectProperties.TestFailures.TestFailure(
                                  test_spec=hw_test_unit1),
                              CrosBisectProperties.TestFailures.TestFailure(
                                  test_spec=hw_test_unit2),
                              CrosBisectProperties.TestFailures.TestFailure(
                                  test_spec=hw_test_unit3),
                          ]
                      })
          }),
      api.properties(
          TestInputProperties(expected_test_child_builders=[
              'bar-postsubmit',
              'foo-postsubmit',
          ])),
  )

  yield api.test(
      'with-validation-props',
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  CrosBisectProperties(test_bisection_percent=20,
                                       test_bisection_count=10)
          }),
      api.properties(
          TestInputProperties(
              expected_test_bisection_percent=20,
              expected_test_bisection_count=10,
          )),
  )
