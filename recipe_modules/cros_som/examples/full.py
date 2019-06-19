# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_som',
]

def RunSteps(api):
  annotation = api.cros_som.get_annotation(
      'hw test results (3)|[FAILED] target.hw.bvt-cq')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertEqual(annotation.bugs, ['1234'])
  api.assertions.assertEqual(annotation.snooze_time_ms, 0)

  annotation = api.cros_som.get_annotation(
      'vm test results (3)|[FAILED] target.vm.suite')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertIsNone(annotation.bugs)
  api.assertions.assertEqual(annotation.snooze_time_ms, 9999000000000)

  api.assertions.assertIsNone(api.cros_som.get_annotation('bad step'))


def GenTests(api):

  yield api.test('basic')

  yield (api.test('malformed_key') +  #
         api.cros_som.get_malformed_key_step_data())
