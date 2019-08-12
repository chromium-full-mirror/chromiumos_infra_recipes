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
  ref = api.gerrit.add_change_comment(gerrit_change, 'my comment')
  api.assertions.assertEqual(ref, 'refs/for/master%m=my%20comment')

def GenTests(api):
  yield api.test('basic')
