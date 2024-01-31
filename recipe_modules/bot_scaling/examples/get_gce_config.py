# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]



def RunSteps(api):
  gce_config = api.bot_scaling.get_current_gce_config(
      api.cros_infra_config.get_bot_policy_config())
  api.assertions.assertEqual(len(gce_config.configs.vms), 4)
  api.assertions.assertEqual(len(gce_config.missing_configs), 1)


def GenTests(api):
  yield api.test('basic')
