# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.gce.api.config.v1.config import Config
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'gce_provider',
]



def RunSteps(api):
  config = api.gce_provider.get_current_config(['prefix-first']).configs
  api.assertions.assertEqual(len(config.vms), 1)

  prefix_map = {'prefix-first': 20, 'prefix-second': 25}
  for prefix, amount in prefix_map.items():
    input_config = Config(prefix=prefix, current_amount=amount)
    config = api.gce_provider.update_gce_config(prefix, input_config)
    api.assertions.assertEqual(amount, config.current_amount)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(
          post_process.StepCommandEquals,
          'gce-provider.config.Update bot group prefix-first', [
              'prpc', 'call', '-format=json', 'gce-provider.appspot.com',
              'config.Configuration.Update'
          ]),
  )
