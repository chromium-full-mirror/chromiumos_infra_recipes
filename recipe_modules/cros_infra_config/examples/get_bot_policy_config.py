# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test getting bot policy configs for ChromeOS and ChromeOSMPA projects."""

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]



def RunSteps(api):
  all_policies = api.cros_infra_config.get_bot_policy_config().bot_policies
  api.assertions.assertEqual(len(all_policies), 1)
  api.assertions.assertEqual(all_policies[0].bot_group, 'cq')

  mpa_policies = api.cros_infra_config.get_bot_policy_config(
      application='ChromeOSMPA').bot_policies
  api.assertions.assertEqual(len(mpa_policies), 1)
  api.assertions.assertEqual(mpa_policies[0].bot_group, 'release-mpa')


def GenTests(api):
  yield api.test('basic')
