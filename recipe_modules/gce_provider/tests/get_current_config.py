#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.gce_provider.tests.get_current_config import GetCurrentConfigProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'deferrals',
    'gce_provider',
]


PROPERTIES = GetCurrentConfigProperties


def RunSteps(api, properties):
  with api.deferrals.raise_exceptions_at_end():
    prefix = properties.prefix
    with api.step.nest('getting config for {}'.format(prefix)):
      api.gce_provider.get_current_config([prefix])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(GetCurrentConfigProperties(prefix='prefix-first')),
      api.post_process(post_process.StepSuccess,
                       'getting config for prefix-first'))

  yield api.test(
      'prefix-with-no-config',
      api.properties(
          GetCurrentConfigProperties(prefix='prefix-should-return-none')),
      api.post_process(post_process.StepSuccess,
                       'getting config for prefix-should-return-none'),
      status='FAILURE',
  )
