# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test git_footers calls."""

DEPS = [
    'recipe_engine/assertions',
    'git_footers',
]


def RunSteps(api):
  api.assertions.assertEqual(api.git_footers.get('HEAD', 'Reviewed-On'),
                             ['HEAD:Reviewed-On'])
  api.assertions.assertEqual(api.git_footers.position_num('HEAD'), 101)


def GenTests(api):
  yield api.test('basic')
