# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'gce_provider',
]

from PB.go.chromium.org.luci.gce.api.config.v1.config import Config


def RunSteps(api):
  config = api.gce_provider.get_current_config(
      ['chromeos-ci-cq-us-central1-b-x32'])
  api.assertions.assertEqual(len(config.vms), 1)

  prefix_map = {'prefix-first': 20, 'prefix-second': 25}
  for prefix, amount in prefix_map.items():
    input_config = Config(prefix=prefix, current_amount=amount)
    config = api.gce_provider.update_gce_config(prefix, input_config)
    api.assertions.assertEqual(amount, config.current_amount)


def GenTests(api):
  yield api.test('basic')
