# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  policies = api.cros_infra_config.get_dut_tracking_config().policies
  api.assertions.assertEqual(len(policies), 1)
  api.assertions.assertEqual(policies[0].name, 'atlas')


def GenTests(api):
  yield api.test('basic')
