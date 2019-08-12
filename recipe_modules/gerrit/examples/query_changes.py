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
  changes = api.gerrit.query_changes(
      'https://chromium-review.googlesource.com',
      [('topic', 'pupr')])
  api.assertions.assertEqual(len(changes), 1)

def GenTests(api):
  yield api.test('basic')
