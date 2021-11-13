# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_plan',
    'gitiles',
]

TEST_TARGET_TEST_REQUIREMENTS_DATA = '''{
    "perTargetTestRequirements": [
        {
            "targetCriteria": {
                "buildTarget": "atlas-kernelnext",
                "builderName": "atlas-kernelnext-release-main"
            },
            "hwTestCfg": {
                "hwTest": [
                    {
                        "common": {
                            "displayName": "atlas-kernelnext-release-main.hw.bvt-tast-cq",
                            "critical": false,
                            "testSuiteGroups": [
                                {
                                    "testSuiteGroup": "default-tast-suites"
                                }
                            ]
                        },
                        "suite": "bvt-tast-cq",
                        "skylabBoard": "atlas",
                        "hwTestSuiteType": "TAST",
                        "pool": "DUT_POOL_QUOTA"
                    }
                 ]
            }
        }
    ]
}'''


def RunSteps(api):
  api.cros_test_plan.get_target_test_requirements_file()
  api.cros_test_plan.generate([Build()], [GerritChange()],
                              GitilesCommit(id='1234abcd'))
  _ = api.cros_test_plan.test_api.all_non_critical_generate_test_plan_response


def GenTests(api):
  yield api.test(
      'basic',
      api.gitiles.get_file(TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.buildbucket.try_build(
          project='chromeos', bucket='cq',
          builder='lts-cq-release-R90-13816.B-orchestrator'),
      api.post_check(post_process.StepCommandContains,
                     'generate test plan.ensure test_planner.ensure_installed',
                     ['chromiumos/infra/test_plan_generator/${platform} prod']),
  )

  yield api.test(
      'parameters-all-set',
      api.properties(
          **{
              "$chromeos/cros_test_plan": {
                  "board_priority_config_path":
                      "something/bpcp.binary_proto",
                  "source_tree_test_config_path":
                      "something/sttp.binary_proto",
                  "target_test_requirements_path":
                      "something/ttrp.binary_proto",
                  "source_gitiles_repo":
                      "chromeos/infra/config",
                  "source_gitiles_branch":
                      "release-R93-14092.B",
              }
          }),
      api.buildbucket.ci_build(project='chromeos', bucket='staging',
                               builder='staging-main-release-orchestrator'),
      api.post_check(
          post_process.StepCommandContains,
          'generate test plan.call test_planner', [
              "--gitiles_repo", "chromeos/infra/config", "--gitiles_branch",
              "release-R93-14092.B", "--board_priority_config",
              "something/bpcp.binary_proto", "--source_tree_config",
              "something/sttp.binary_proto", "--target_test_requirements",
              "something/ttrp.binary_proto"
          ]))

  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='staging-main-release-orchestrator',
      ),
      api.post_check(
          post_process.StepCommandContains,
          'generate test plan.ensure test_planner.ensure_installed',
          ['chromiumos/infra/test_plan_generator/${platform} staging']),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{
              "$chromeos/cros_test_plan": {
                  "test_plan_generator_cipd_package": "test_plan_generator_foo",
                  "test_plan_generator_cipd_ref": "bar",
              }
          }),
      api.post_check(post_process.StepCommandContains,
                     'generate test plan.ensure test_planner.ensure_installed',
                     ['test_plan_generator_foo bar']),
  )
