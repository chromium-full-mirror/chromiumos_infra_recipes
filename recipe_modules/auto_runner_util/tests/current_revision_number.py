# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for current_revision_number prop."""

from recipe_engine.post_process import DropExpectation

from RECIPE_MODULES.chromeos.auto_runner_util.api import EnhancedChangeInfo

DEPS = [
    'recipe_engine/assertions', 'auto_runner_util', 'recipe_engine/properties'
]


def RunSteps(api):
  verification = {
      5590294: 2,
      5590423: 1,
      5590242: 1,
      5588289: 1,
      5590139: 2,
      5590140: 2,
      5590141: 2,
  }
  change_infos = api.properties['changes']
  ecs = []
  for c in change_infos:
    ecs.append(EnhancedChangeInfo(c, 'dummy_host', None))
  api.assertions.assertEqual(len(ecs), len(verification))
  for ec in ecs:
    api.assertions.assertTrue(
        ec.current_revision_number == verification.get(ec.change))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          changes=api.auto_runner_util.get_test_output_as_jsonobj(
              'test_output.json')), api.post_process(DropExpectation))
