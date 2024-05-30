# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfig
from RECIPE_MODULES.chromeos.failures.api import Failure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  builder_configs = {
      'noncritical builder':
          BuilderConfig(
              general=BuilderConfig.General(critical={'value': False})),
      'critical builder':
          BuilderConfig(
              general=BuilderConfig.General(critical={'value': True})),
  }

  link_map = {'a title': 'someurl'}
  in_failures = [
      Failure(kind='build', title='title', link_map=link_map, fatal=True,
              id='noncritical builder')
  ]
  with api.step.nest('test step') as pres:
    out_failures = api.failures.update_non_critical_build_failures(
        in_failures, builder_configs, pres)
    api.assertions.assertFalse(out_failures[0].fatal)

    in_failures = [
        Failure(kind='build', title='title', link_map=link_map, fatal=True,
                id='critical builder')
    ]
    out_failures = api.failures.update_non_critical_build_failures(
        in_failures, builder_configs, pres)
    api.assertions.assertTrue(out_failures[0].fatal)


def GenTests(api):
  yield api.test('basic')
