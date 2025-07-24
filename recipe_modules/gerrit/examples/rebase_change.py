# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test api.gerrit.add_change_comment."""

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
  api.gerrit.rebase_change_remote(gerrit_change)
  api.gerrit.rebase_change_remote(gerrit_change, 'deadbeef')


def GenTests(api):
  yield api.test('basic')
