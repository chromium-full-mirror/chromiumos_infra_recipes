# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.builder_config import BuilderConfig

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

  in_failures = [
      api.failures.Failure(kind='build', title='title', url='someurl',
                           fatal=True, id='noncritical builder')
  ]
  out_failures = api.failures.update_non_critical_failures(
      in_failures, builder_configs)
  api.assertions.assertFalse(out_failures[0].fatal)

  in_failures = [
      api.failures.Failure(kind='build', title='title', url='someurl',
                           fatal=True, id='critical builder')
  ]
  out_failures = api.failures.update_non_critical_failures(
      in_failures, builder_configs)
  api.assertions.assertTrue(out_failures[0].fatal)


def GenTests(api):
  yield api.test('basic')
