# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import PackageInfo

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

  with api.step.nest('one compile failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed compilation for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_compile_failure/category_package-name_log\)',
        api.failures.set_compile_failed_packages, test_step, [(PackageInfo(
            package_name='package-name', category='category'), 'test log')])
  with api.step.nest('one test failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed unit tests for \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_test_failure/category_package-name_log\)',
        api.failures.set_test_failed_packages, test_step, [(PackageInfo(
            package_name='package-name', category='category'), 'test log')])

  with api.step.nest('multiple compile failures') as test_step:
    api.assertions.assertRaises(
        api.step.StepFailure, api.failures.set_compile_failed_packages,
        test_step,
        [(PackageInfo(package_name='package1'), 'test log for package1'),
         (PackageInfo(package_name='package2'), 'test log for package2')])

  with api.step.nest('multiple test failures') as test_step:
    api.assertions.assertRaises(
        api.step.StepFailure, api.failures.set_test_failed_packages, test_step,
        [(PackageInfo(package_name='package3'), 'test log for package3'),
         (PackageInfo(package_name='package4'), 'test log for package4')])

  with api.step.nest('test3') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_compile_failed_packages,
                                test_step,
                                [(PackageInfo(package_name='package'), '')])


def GenTests(api):
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test('basic', api.buildbucket.build(build_message))
