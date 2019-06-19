# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_som',
]

from PB.recipe_modules.chromeos.cros_som.cros_som import CrosSomProperties


def RunSteps(api):
  annotation = api.cros_som.get_annotation(
      'ensure manifest cq-depend fulfilled|git log (3)')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertEqual(annotation.bugs, ['974630'])
  api.assertions.assertEqual(annotation.snooze_time_ms, 1560838289688)

  annotation = api.cros_som.get_annotation(
      'create sysroot|call chromite.api.SysrootService/Create|call build API script'
  )
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertIsNone(annotation.bugs)
  api.assertions.assertEqual(annotation.snooze_time_ms, 0)

  api.assertions.assertIsNone(api.cros_som.get_annotation('bad step'))


def GenTests(api):

  yield api.test('basic')

  yield (api.test('malformed_key') +  #
         api.cros_som.get_malformed_key_step_data())
