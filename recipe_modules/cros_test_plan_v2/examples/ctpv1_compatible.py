# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]

from recipe_engine import post_process

from google.protobuf import text_format

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.testplans.common import ProtoBytes
from PB.testplans.generate_test_plan import GenerateTestPlanRequest


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

  generate_test_plan_resp = api.cros_test_plan_v2.generate_hw_test_plans(
      [
          api.cros_test_plan_v2.StarlarkPackage(root='root1',
                                                main='example1.star'),
          api.cros_test_plan_v2.StarlarkPackage(root='root2',
                                                main="example2.star"),
      ],
      generate_test_plan_request=GenerateTestPlanRequest(
          buildbucket_protos=[ProtoBytes(serialized_proto='abc123')],
      ),
  )

  api.assertions.assertEqual(
      api.cros_test_plan_v2.test_api.generate_test_plan_response(),
      generate_test_plan_resp,
  )

  with api.assertions.assertRaisesRegexp(
      ValueError,
      'generate_test_plan_request should be set iff the generate_ctpv1_format property is set'
  ):
    api.cros_test_plan_v2.generate_hw_test_plans([
        api.cros_test_plan_v2.StarlarkPackage(root='root1',
                                              main='example1.star'),
        api.cros_test_plan_v2.StarlarkPackage(root='root2',
                                              main="example2.star"),
    ],
                                                )


def GenTests(api):

  yield api.test(
      'basic',
      api.properties(
          **{'$chromeos/cros_test_plan_v2': {
              'generate_ctpv1_format': True
          }}),
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
      api.post_process(
          post_process.StepCommandContains,
          'generate hw test plans.docker run',
          [
              '-ctpv1',
              '-configbundlelist',
              '/input/configs.jsonproto',
              '-generatetestplanreq',
              '/input/generatetestplanreq.binaryproto',
              '-dutattributes',
              '/input/dut_attributes.jsonproto',
              '-buildmetadata',
              '/input/build_metadata.jsonproto',
              '-out',
              '/input/generatetestplanresp.binaryproto',
          ],
      ),
  )
