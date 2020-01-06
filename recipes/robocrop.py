# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in the Chrome OS pool."""

from PB.recipes.chromeos.robocrop import RoboCropProperties

DEPS = [
    'recipe_engine/step',
    'buildbucket_stats',
    'cros_infra_config',
    'easy',
]

PROPERTIES = RoboCropProperties

def RunSteps(api, properties):
  pools_to_monitor = properties.pools_to_monitor or ['cq', 'postsubmit']

  with api.step.nest('monitor bot pools'):
    status_map = {}
    for pool in pools_to_monitor:
      status_map[pool] = api.buildbucket_stats.get_bucket_status(pool)

    # Save this data to output.properties.
    api.easy.set_property_step('current_bot_data', status_map)

  with api.step.nest('scale bot pools'):
    with api.step.nest('read bot policies'):
      api.cros_infra_config.get_bot_policies()


def GenTests(api):
  yield (api.test('basic'))