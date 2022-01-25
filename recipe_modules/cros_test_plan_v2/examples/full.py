# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]

from recipe_engine import post_process

from google.protobuf import text_format, json_format

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.chromiumos.test.api.coverage_rule import CoverageRule
from PB.chromiumos.test.api.v1.plan import HWTestPlan


def RunSteps(api):
  relevant_plans = api.cros_test_plan_v2.relevant_plans([
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
      relevant_plans,
      [
          api.cros_test_plan_v2.test_api.kernel_source_test_plan(),
          api.cros_test_plan_v2.test_api.fp_source_test_plan(),
      ],
  )

  hw_test_plans = api.cros_test_plan_v2.generate_hw_test_plans([
      api.cros_test_plan_v2.StarlarkPackage(root='root1', main='example1.star'),
      api.cros_test_plan_v2.StarlarkPackage(root='root2', main="example2.star"),
  ])
  api.assertions.assertEqual(
      hw_test_plans,
      [
          HWTestPlan(
              coverage_rules=[
                  CoverageRule(name='kernel:4.4'),
                  CoverageRule(name='kernel:5.2')
              ],
          ),
          HWTestPlan(
              coverage_rules=[
                  CoverageRule(name='wifiA'),
              ],
          ),
      ],
  )


def GenTests(api):

  yield api.test(
      'basic',
      api.step_data(
          'find relevant plans.list output files',
          api.file.listdir(['relevant_plan_1.textpb',
                            'relevant_plan_2.textpb']),
      ),
      api.step_data(
          'find relevant plans.read output [CLEANUP]/test_plan_tmp_1/relevant_plan_1.textpb',
          api.raw_io.output(
              text_format.MessageToString(
                  api.cros_test_plan_v2.kernel_source_test_plan(),
              ),
          ),
      ),
      api.step_data(
          'find relevant plans.read output [CLEANUP]/test_plan_tmp_1/relevant_plan_2.textpb',
          api.raw_io.output(
              text_format.MessageToString(
                  api.cros_test_plan_v2.fp_source_test_plan(),
              ),
          ),
      ),
      api.step_data(
          'generate hw test plans.read output [CLEANUP]/tmp_tmp_1/hw_test_plans.jsonproto',
          api.raw_io.output('\n'.join(
              json_format.MessageToJson(rule).replace('\n', '')
              for rule in api.cros_test_plan_v2.hw_test_plans())),
      ),
      api.post_process(
          post_process.StepCommandContains,
          'find relevant plans.call test_plan',
          [
              '[START_DIR]/cipd/test_plan',
              'relevant-plans',
              '-loglevel',
              'debug',
              '-cl',
              'https://chromium-review.googlesource.com/c/src/projectA/+/123/3',
              '-cl',
              'https://chromium-review.googlesource.com/c/src/projectB/+/456/7',
              '-out',
              '[CLEANUP]/test_plan_tmp_1',
          ],
      ),
  )
