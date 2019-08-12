# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
]


def RunSteps(api):
  gerrit_change = GerritChange(
      project='chromiumos/chromite', host='crrev.com', patchset=42, change=1)
  api.assertions.assertTrue(api.gerrit.has_chromite_changes([gerrit_change]))
  gerrit_change.project = 'something_else'
  api.assertions.assertFalse(api.gerrit.has_chromite_changes([gerrit_change]))
  api.assertions.assertFalse(api.gerrit.has_chromite_changes([]))

def GenTests(api):
  yield api.test('basic')
