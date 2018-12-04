# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'recipe_engine/buildbucket',

  'changes',
]


def RunSteps(api):
  change = api.changes.get_changes()[0]
  assert change.project == 'chromium/src'
  assert change.url == 'https://chromium-review.googlesource.com/91827'

def GenTests(api):
  yield (api.test('basic') +
         api.buildbucket.try_build())
