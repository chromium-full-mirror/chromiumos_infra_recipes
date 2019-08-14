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
  labels = {
      api.gerrit.Label.CODE_REVIEW: 2,
      api.gerrit.Label.VERIFIED: 1,
  }
  ref = api.gerrit.set_change_labels(gerrit_change, labels)
  api.assertions.assertEqual(
      ref, 'refs/for/master%l=Code-Review+2,l=Verified+1')

def GenTests(api):
  yield api.test('basic')
