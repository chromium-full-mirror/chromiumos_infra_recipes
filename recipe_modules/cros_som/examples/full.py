# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_som',
]



def RunSteps(api):
  annotation = api.cros_som.get_annotation('step with linked bugs')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertEqual(annotation.bugs, ['1234'])
  api.assertions.assertEqual(annotation.snooze_time_ms, 0)
  api.assertions.assertIsNone(api.cros_som.get_silence_reason(annotation))

  annotation = api.cros_som.get_annotation('snoozed step')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertIsNone(annotation.bugs)
  api.assertions.assertEqual(annotation.snooze_time_ms, 9999000000000)
  api.assertions.assertEqual(
      api.cros_som.get_silence_reason(annotation),
      'step failure is snoozed by Sheriff-o-Matic.')

  annotation = api.cros_som.get_annotation(
      'step with no snoozes or linked bugs')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertIsNone(annotation.bugs)
  api.assertions.assertEqual(annotation.snooze_time_ms, 0)
  api.assertions.assertIsNone(api.cros_som.get_silence_reason(annotation))

  annotation = api.cros_som.get_annotation('step in group with snooze')
  api.assertions.assertIsNotNone(annotation)
  api.assertions.assertIsNone(annotation.bugs)
  api.assertions.assertEqual(annotation.snooze_time_ms, 0)
  api.assertions.assertEqual(annotation.group_id, '123')
  api.assertions.assertEqual(
      api.cros_som.get_silence_reason(annotation),
      'step failure is snoozed by Sheriff-o-Matic.')

  api.assertions.assertIsNone(api.cros_som.get_annotation('bad step'))


def GenTests(api):
  yield api.test('basic')
