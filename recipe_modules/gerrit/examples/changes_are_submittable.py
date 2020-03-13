# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
]

def RunSteps(api):
  # TODO(evanhernandez): Need to normalize how we handle test data.
  change = GerritChange(
      host='chromium-review.googlesource.com',
      change=91827,
      patchset=1,
  )

  api.gerrit.assert_changes_submittable([change])
  api.assertions.assertRaises(
      api.step.StepFailure,
      api.gerrit.assert_changes_submittable,
      [change],
      test_output_data=api.gerrit.test_api.test_changes_are_submittable(
          errors=['could not cherry pick']))
  api.gerrit.test_api.simulated_changes_are_submittable(submittable=False)


def GenTests(api):
  yield api.test('basic')
