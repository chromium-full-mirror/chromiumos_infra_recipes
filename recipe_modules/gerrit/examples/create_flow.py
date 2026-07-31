# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test api.gerrit.create_flow."""

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
  expressions = [{
      'condition': '-label:Commit-Queue',
      'action': {
          'name': 'add-reviewer',
          'parameters': ['cros-ec-champion@google.com'],
      },
  }]
  api.gerrit.create_flow(gerrit_change, expressions)


def GenTests(api):
  yield api.test('basic')
