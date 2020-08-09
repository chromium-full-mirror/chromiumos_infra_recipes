# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'gerrit',
]


def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )
  # TODO(evanhernandez): An assertion would be nice...
  api.gerrit.add_change_comment(gerrit_change, 'my comment')


def GenTests(api):
  yield api.test('basic')
