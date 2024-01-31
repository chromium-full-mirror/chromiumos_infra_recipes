# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_sdk.examples.test import TestInputProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_sdk',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(properties.expected_long_timeouts,
                             api.cros_sdk.long_timeouts)
  # Testing boolean stickiness.
  api.cros_sdk.long_timeouts = True
  api.assertions.assertTrue(api.cros_sdk.long_timeouts)
  api.cros_sdk.long_timeouts = False
  api.assertions.assertTrue(api.cros_sdk.long_timeouts)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-force_long_timeouts',
      api.properties(**{'$chromeos/cros_sdk': {
          'force_long_timeouts': True
      }}, expected_long_timeouts=True),
      api.post_process(post_process.DropExpectation))
