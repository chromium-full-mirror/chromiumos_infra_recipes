# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  _ = api.gerrit.gerrit_patch_sets

  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )

  # Difficult to assert on, so just call the function.
  api.gerrit.abandon_change(gerrit_change, message='my comment')


def GenTests(api):
  yield api.test('basic')
