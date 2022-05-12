# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  gce_config = api.bot_scaling.get_current_gce_config(
      api.cros_infra_config.get_bot_policy_config())
  api.assertions.assertEqual(len(gce_config.vms), 4)


def GenTests(api):
  yield api.test('basic')
