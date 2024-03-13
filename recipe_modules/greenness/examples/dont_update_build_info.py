# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittest noop update_build_info() when not publishing results"""

from recipe_engine import post_process

DEPS = [
    'greenness',
    'test_util',
]


def RunSteps(api):
  builds = [
      api.test_util.test_api.test_child_build(
          build_target_name='betty', output_properties={
              'builderGreenness': '78'
          }).message
  ]
  api.greenness.update_build_info(builds)


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
