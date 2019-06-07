# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_history',
]


def RunSteps(api):
  # Puke and die when duplicate test IDs provided.
  api.assertions.assertRaises(ValueError, api.cros_history.set_passed_tests,
                              ['a', 'a', 'b'])

  # Otherwise just make sure the build property is set correctly.
  api.cros_history.set_passed_tests(['a', 'b'])


def GenTests(api):
  expect = ['a', 'b']
  yield (
      api.test('basic') +  #
      api.post_check(
          lambda check, steps: check(steps['set passed_tests'].output_properties['passed_tests'] == expect)
      ))
