# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'failures',
]

from PB.chromiumos.common import PackageInfo

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):

  with api.step.nest('no failures') as test_step:
    # Call with no failed packages, should noop.
    api.failures.set_failed_packages(test_step, [])

  with api.step.nest('one failure') as test_step:
    api.assertions.assertRaisesRegexp(
        api.step.StepFailure, r'failed to install \[category/package-name]'
        r'\(https://logs.chromium.org/logs/chromeos/logdog/prefix/'
        r'\+/u/one_failure/category_package-name_log\)',
        api.failures.set_failed_packages, test_step, [(PackageInfo(
            package_name='package-name', category='category'), 'test log')])

  with api.step.nest('multiple failures') as test_step:
    api.assertions.assertRaises(
        api.step.StepFailure, api.failures.set_failed_packages, test_step,
        [(PackageInfo(package_name='package1'), 'test log for package1'),
         (PackageInfo(package_name='package2'), 'test log for package2')])
  with api.step.nest('test3') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_failed_packages, test_step,
                                [(PackageInfo(package_name='package'), '')])


def GenTests(api):
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test('basic', api.buildbucket.build(build_message))
