# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for setting package failures."""

from PB.chromiumos.common import PackageInfo
from PB.recipe_modules.chromeos.failures.failures import PackageFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):

  with api.step.nest('no failures') as test_step:
    # Call with no failed packages, should noop.
    api.failures.set_compile_failed_packages(test_step, [])
    api.failures.set_test_failed_packages(test_step, [])

  package_info_0 = PackageInfo(package_name='package-name', category='category')
  package_info_1 = PackageInfo(package_name='package1')
  package_info_2 = PackageInfo(package_name='package2')
  package_info_3 = PackageInfo(package_name='package3')
  package_info_4 = PackageInfo(package_name='package4')
  package_info_5 = PackageInfo(package_name='package')

  with api.step.nest('one compile failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed compilation for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_compile_failure/category_package-name_log\)',
        api.failures.set_compile_failed_packages, test_step,
        [(package_info_0, 'test log')])

  with api.step.nest('one test failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed unit tests for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_test_failure/category_package-name_log\)',
        api.failures.set_test_failed_packages, test_step, [(PackageInfo(
            package_name='package-name', category='category'), 'test log')])

  with api.step.nest('multiple compile failures') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_compile_failed_packages,
                                test_step,
                                [(package_info_1, 'test log for package1'),
                                 (package_info_2, 'test log for package2')])

  with api.step.nest('multiple test failures') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_test_failed_packages,
                                test_step,
                                [(package_info_3, 'test log for package3'),
                                 (package_info_4, 'test log for package4')])

  with api.step.nest('test3') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_compile_failed_packages,
                                test_step, [(package_info_5, '')])

  api.assertions.assertCountEqual(api.failures.package_failures, [
      PackageFailure(package=package_info_0, phase='COMPILE'),
      PackageFailure(package=package_info_0, phase='TEST'),
      PackageFailure(package=package_info_1, phase='COMPILE'),
      PackageFailure(package=package_info_2, phase='COMPILE'),
      PackageFailure(package=package_info_3, phase='TEST'),
      PackageFailure(package=package_info_4, phase='TEST'),
      PackageFailure(package=package_info_5, phase='COMPILE'),
  ])

def GenTests(api):
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test('basic', api.buildbucket.build(build_message))
