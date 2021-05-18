# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan_v2',
]

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange


def RunSteps(api):
  coverage_rules = api.cros_test_plan_v2.generate([
      GerritChange(
          host="chromium-review.googlesource.com",
          project="src/projectA",
          change=123,
          patchset=3,
      ),
      GerritChange(
          host="chromium-review.googlesource.com",
          project="src/projectB",
          change=456,
          patchset=7,
      ),
  ])

  api.assertions.assertListEqual(
      coverage_rules,
      [
          api.cros_test_plan_v2.test_api.kernel_coverage_rule(),
          api.cros_test_plan_v2.test_api.fp_coverage_rule(),
      ],
  )


def GenTests(api):

  yield api.test(
      'basic',
      api.post_process(
          post_process.StepCommandContains,
          'generate test plan v2.call test_plan',
          [
              '[START_DIR]/cipd/test_plan',
              'generate',
              '-loglevel',
              'debug',
              '-cl',
              'https://chromium-review.googlesource.com/c/src/projectA/+/123/3',
              '-cl',
              'https://chromium-review.googlesource.com/c/src/projectB/+/456/7',
              '-output',
              '[CLEANUP]/test_plan_tmp_1/output.jsonproto',
          ],
      ),
  )
