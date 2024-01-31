# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_scaling',
    'cros_infra_config',
]



def RunSteps(api):
  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config(
      repeated=2)
  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  robocrop_action = api.bot_scaling.get_robocrop_action(
      bot_policy_config, api.bot_scaling.test_api.gce_provider_config(),
      swarming_stats=swarming_stats)
  for appl in robocrop_action.appl_resource_utilization:
    api.assertions.assertEqual(appl.application, 'chromeos')
    for resource in appl.resource_utilization:
      if resource.region == 'global':
        api.assertions.assertEqual(resource.vms, 120)
        api.assertions.assertEqual(resource.cpus, 480)
        api.assertions.assertEqual(resource.memory_gb, 1920)
        api.assertions.assertEqual(resource.max_cpus, 1200)
      if resource.region == 'first':
        api.assertions.assertEqual(resource.vms, 30)
        api.assertions.assertEqual(resource.cpus, 120)
        api.assertions.assertEqual(resource.memory_gb, 480)
      api.assertions.assertIsNotNone(resource)


def GenTests(api):
  yield api.test('basic')
