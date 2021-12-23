# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]

from PB.chromiumos.common import PackageInfo


def RunSteps(api):
  with api.step.nest('test1') as test_step:
    # Call with no failed packages, should noop.
    api.failures.set_failed_packages(test_step, [])

    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_failed_packages, test_step,
                                [(PackageInfo(package_name='package'), 'test')])
  with api.step.nest('test2') as test_step:
    api.assertions.assertRaises(
        api.step.StepFailure, api.failures.set_failed_packages, test_step,
        [(PackageInfo(package_name='package1'), 'test log for package1'),
         (PackageInfo(package_name='package2'), 'test log for package2')])
  with api.step.nest('test3') as test_step:
    api.assertions.assertRaises(api.step.StepFailure,
                                api.failures.set_failed_packages, test_step,
                                [(PackageInfo(package_name='package'), '')])


def GenTests(api):
  yield api.test('basic')
