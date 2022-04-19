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
  all_policies = api.cros_infra_config.get_bot_policy_config(
      application='Chrome').bot_policies
  api.assertions.assertEqual(len(all_policies), 1)
  api.assertions.assertEqual(all_policies[0].bot_group, 'try-test')


def GenTests(api):
  yield api.test('basic')
