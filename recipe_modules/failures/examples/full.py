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
  api.failures.raise_failed_packages([])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_packages,
                              [PackageInfo(package_name='package')])


def GenTests(api):
  yield api.test('basic')
