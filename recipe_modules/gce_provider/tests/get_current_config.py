#  -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/properties',
    'recipe_engine/step', 'gce_provider'
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.gce_provider.tests.get_current_config \
    import GetCurrentConfigProperties

PROPERTIES = GetCurrentConfigProperties


def RunSteps(api, properties):
  prefix = properties.prefix
  with api.step.nest('getting config for {}'.format(prefix)):
    api.gce_provider.get_current_config([prefix])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(GetCurrentConfigProperties(prefix="prefix-first")),
      api.post_process(post_process.StepSuccess,
                       'getting config for prefix-first'))

  yield api.test(
      'prefix with no config',
      api.properties(
          GetCurrentConfigProperties(prefix="prefix-should-return-none")),
      api.post_process(post_process.StepException,
                       'getting config for prefix-should-return-none'))
