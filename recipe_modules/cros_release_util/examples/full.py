# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_release_util',
]


def RunSteps(api):
  api.assertions.assertEqual(
      api.cros_release_util.release_builder_name('zork'), 'zork-release-main')
  api.assertions.assertEqual(
      api.cros_release_util.release_builder_name('zork', staging=True),
      'staging-zork-release-main')
  api.assertions.assertEqual(
      api.cros_release_util.release_builder_name('zork',
                                                 branch='release-R98-14388.B'),
      'zork-release-R98-14388.B')


def GenTests(api):
  yield api.test('basic')
