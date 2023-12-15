# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format
from google.protobuf import text_format

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import FALLBACK_DEFAULT_SOURCE_TEST_PLAN
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import LEGACY_DEFAULT_VM_TEST_PLAN_BETTY_ARC_R
from RECIPE_MODULES.chromeos.cros_test_plan_v2.api import VM_LAB_TEST_PLAN

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_test_plan_v2',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  relevant_plans = api.cros_test_plan_v2.relevant_plans([
      GerritChange(
          host='chromium-review.googlesource.com',
          project='src/projectA',
          change=123,
          patchset=3,
      )
  ])

  expected_plans = [
      json_format.Parse(p, source_test_plan_pb2.SourceTestPlan())
      for p in api.properties['expected_plans']
  ]
  api.assertions.assertCountEqual(relevant_plans, expected_plans)


def GenTests(api):

  yield api.test(
      'no-experiment',
      api.step_data(
          'find relevant plans.src/projectA.list output files',
          api.file.listdir(['relevant_plan_1.textpb']),
      ),
      api.step_data(
          'find relevant plans.src/projectA.read output [CLEANUP]/test_plan_tmp_1/relevant_plan_1.textpb',
          api.raw_io.output(
              text_format.MessageToString(
                  FALLBACK_DEFAULT_SOURCE_TEST_PLAN,
              ),
          ),
      ),
      api.properties(expected_plans=[
          json_format.MessageToJson(FALLBACK_DEFAULT_SOURCE_TEST_PLAN),
          json_format.MessageToJson(LEGACY_DEFAULT_VM_TEST_PLAN_BETTY_ARC_R)
      ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'experiment-enabled',
      api.buildbucket.try_build(experiments=['chromeos.build_cq.vmlab_cq']),
      api.step_data(
          'find relevant plans.src/projectA.list output files',
          api.file.listdir(['relevant_plan_1.textpb']),
      ),
      api.step_data(
          'find relevant plans.src/projectA.read output [CLEANUP]/test_plan_tmp_1/relevant_plan_1.textpb',
          api.raw_io.output(
              text_format.MessageToString(
                  FALLBACK_DEFAULT_SOURCE_TEST_PLAN,
              ),
          ),
      ),
      api.properties(expected_plans=[
          json_format.MessageToJson(FALLBACK_DEFAULT_SOURCE_TEST_PLAN),
          json_format.MessageToJson(VM_LAB_TEST_PLAN)
      ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'experiment-enabled-vm-test-plan-not-run',
      api.buildbucket.try_build(experiments=['chromeos.build_cq.vmlab_cq']),
      api.step_data(
          'find relevant plans.src/projectA.list output files',
          api.file.listdir(['relevant_plan_1.textpb']),
      ),
      api.step_data(
          'find relevant plans.src/projectA.read output [CLEANUP]/test_plan_tmp_1/relevant_plan_1.textpb',
          api.raw_io.output(
              text_format.MessageToString(
                  api.cros_test_plan_v2.kernel_source_test_plan(),
              ),
          ),
      ),
      api.properties(expected_plans=[
          json_format.MessageToJson(
              api.cros_test_plan_v2.kernel_source_test_plan()),
      ]),
      api.post_process(post_process.DropExpectation),
  )
