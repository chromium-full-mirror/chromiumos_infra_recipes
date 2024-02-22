# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Testing whether cq-depended CLs are being tested in the run."""

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'lfg_util',
]


def RunSteps(api):
  example_input = {
      '123': [{
          'project': 'chromiumos/kernel',
          '_change_number': 456,
          '_revision_number': 3,
          'host': 'chromium-review.googlesource.com'
      }],
      '345': [{
          'project': 'chromeos/kernel-internal',
          '_change_number': 654,
          '_revision_number': 1,
          'host': 'chrome-internal-review.googlesource.com'
      }],
  }
  expected_changes = [
      GerritChange(change=456, host='chromium-review.googlesource.com',
                   project='chromiumos/kernel', patchset=3),
      GerritChange(change=654, host='chrome-internal-review.googlesource.com',
                   project='chromeos/kernel-internal', patchset=1),
  ]
  api.assertions.assertEqual(expected_changes,
                             api.lfg_util.json_to_gerritchanges(example_input))
  api.assertions.assertEqual([], api.lfg_util.json_to_gerritchanges(None))


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )
