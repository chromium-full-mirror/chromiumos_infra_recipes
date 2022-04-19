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
  all_scenarios = api.cros_infra_config.get_vm_retry_config().suite_scenarios
  api.assertions.assertEqual(len(all_scenarios), 2)
  api.assertions.assertEqual(all_scenarios[0].test_name, 'arc.Boot')


def GenTests(api):
  yield api.test('basic')
