# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]


def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )

  api.assertions.assertEqual(
      api.gerrit.get_change_description(gerrit_change),
      api.gerrit.test_api.test_gerrit_change_description())


def GenTests(api):
  yield api.test('basic')
