# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

from recipe_engine import post_process

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'build_menu',
    'cros_test_plan',
    'gitiles',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

TEST_TARGET_TEST_REQUIREMENTS_DATA = b'''{
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
  api.cros_test_plan.get_target_test_requirements()
  api.cros_test_plan.generate_target_test_requirements_config(paygen=True)
  api.cros_test_plan.generate([Build()], [GerritChange()],
                              GitilesCommit(id='1234abcd'))
  _ = api.cros_test_plan.test_api.reduced_criticality_generate_test_plan_response
  _ = api.cros_test_plan.test_api.all_non_critical_generate_test_plan_response


def GenTests(api):
  yield api.test(
      'basic',
      api.gitiles.get_file(TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='release-R90-13816.B-cq-orchestrator'),
  )

  yield api.test(
      'parameters-all-set',
      api.properties(
          **{
              '$chromeos/cros_test_plan': {
                  'board_priority_config_path':
                      'something/bpcp.binary_proto',
                  'source_tree_test_config_path':
                      'something/sttp.binary_proto',
                  'target_test_requirements_path':
                      'something/ttrp.binary_proto',
                  'source_gitiles_repo':
                      'chromeos/infra/config',
                  'source_gitiles_branch':
                      'release-R93-14092.B',
              }
          }),
      api.buildbucket.ci_build(project='chromeos', bucket='staging',
                               builder='staging-release-main-orchestrator'),
      api.post_check(
          post_process.StepCommandContains,
          'generate test plan.call test_planner', [
              '--gitiles_repo', 'chromeos/infra/config', '--gitiles_branch',
              'release-R93-14092.B', '--board_priority_config',
              'something/bpcp.binary_proto', '--source_tree_test_config',
              'something/sttp.binary_proto', '--target_test_requirements',
              'something/ttrp.binary_proto'
          ]))

  generate_test_config_output = '''{
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

  yield api.test(
      'generate-test-config',
      api.properties(
          **{
              '$chromeos/cros_test_plan': {
                  'board_priority_config_path':
                      'something/bpcp.binary_proto',
                  'source_tree_test_config_path':
                      'something/sttp.binary_proto',
                  'target_test_requirements_path':
                      'something/ttrp.binary_proto',
                  'source_gitiles_repo':
                      'chromeos/infra/config',
                  'source_gitiles_branch':
                      'release-R93-14092.B',
                  'generate_target_test_requirements_from_source':
                      True,
                  'use_prod_config':
                      True,
              }
          }),
      api.buildbucket.ci_build(project='chromeos', bucket='staging',
                               builder='release-main-orchestrator'),
      api.step_data('generate target test requirements.generate_test_config',
                    stdout=api.raw_io.output(generate_test_config_output)),
      api.post_check(post_process.StepCommandContains,
                     'generate target test requirements.generate_test_config', [
                         './board_config/generate_test_config',
                         'eve-release-main,kukui-release-main'
                     ]),
      api.post_check(post_process.StepCommandContains,
                     'generate test plan.call test_planner', [
                         '--target_test_requirements_repo',
                         '[CLEANUP]/chromiumos_workspace/src/config-internal'
                     ]))

  yield api.build_menu.test(
      'generate-test-config-child',
      api.properties(
          **{
              '$chromeos/cros_test_plan': {
                  'board_priority_config_path':
                      'something/bpcp.binary_proto',
                  'source_tree_test_config_path':
                      'something/sttp.binary_proto',
                  'target_test_requirements_path':
                      'something/ttrp.binary_proto',
                  'source_gitiles_repo':
                      'chromeos/infra/config',
                  'source_gitiles_branch':
                      'release-R93-14092.B',
                  'generate_target_test_requirements_from_source':
                      True,
              }
          }),
      api.buildbucket.ci_build(project='chromeos', bucket='staging',
                               builder='eve-release-main'),
      api.step_data('generate target test requirements.generate_test_config',
                    stdout=api.raw_io.output(generate_test_config_output)),
      api.post_check(post_process.StepCommandContains,
                     'generate target test requirements.generate_test_config', [
                         './board_config/generate_test_config',
                         'eve-release-main',
                         '--branch',
                         'main',
                     ]), build_target='staging-eve',
      builder='staging-eve-release-main', bucket='release')

  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='staging-release-main-orchestrator',
      ),
      api.post_check(
          post_process.StepCommandContains,
          'generate test plan.ensure test_plan_generator.ensure_installed', [
              'chromiumos/infra/test_plan_generator/${platform} wzCA5zCcIkg0uYroNN91fpH1oQLMVHYaXM8RS9SuQwUC'
          ]),
  )
