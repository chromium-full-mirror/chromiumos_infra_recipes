# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import CrosTestPlanV2Properties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'git_footers',
    'orch_menu',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.orch_menu.setup_orchestrator():
    # Test data.
    build_1 = api.test_util.test_api.test_child_build(
        build_target_name='target1', builder_name='target1-env').message
    build_2 = api.test_util.test_api.test_child_build(
        build_target_name='target2', builder_name='target2-env',
        critical='NO').message
    build_3 = api.test_util.test_api.test_child_build(
        build_target_name='target3', builder_name='target3-env').message
    builds = [
        build_1,
        build_2,
        build_3,
    ]

    child_specs = [
        BuilderConfig.Orchestrator.ChildSpec(
            name=build_1.builder.builder,
            collect_handling=BuilderConfig.Orchestrator.ChildSpec.COLLECT),
        BuilderConfig.Orchestrator.ChildSpec(
            name=build_2.builder.builder, collect_handling=BuilderConfig
            .Orchestrator.ChildSpec.COLLECT_AFTER_HW_TEST),
        BuilderConfig.Orchestrator.ChildSpec(
            name=build_3.builder.builder,
            collect_handling=BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT),
    ]

    # Function call.
    collect_when_dict = api.orch_menu.categorize_builds_by_collect_handling(
        child_specs, builds)

    # For simplicity, assert on the names of the builders rather than the whole
    # build.
    actual_collect_builders = [
        b.builder.builder for b in collect_when_dict.get(
            BuilderConfig.Orchestrator.ChildSpec.COLLECT, [])
    ]
    actual_collect_after_builders = [
        b.builder.builder for b in collect_when_dict.get(
            BuilderConfig.Orchestrator.ChildSpec.COLLECT_AFTER_HW_TEST, [])
    ]
    actual_no_collect_builders = [
        b.builder.builder for b in collect_when_dict.get(
            BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT, [])
    ]

    # If the test does not pass in expected values, the default is to categorize
    # the builders using the collect handling value from the child spec.
    expected_collect_builders = api.properties.get('expected_collect_builders',
                                                   ['target1-env'])
    expected_collect_after_builders = api.properties.get(
        'expected_collect_after_builders', ['target2-env'])
    expected_no_collect_builders = api.properties.get(
        'expected_no_collect_builders', ['target3-env'])

    api.assertions.assertCountEqual(expected_collect_builders,
                                    actual_collect_builders)
    api.assertions.assertCountEqual(expected_collect_after_builders,
                                    actual_collect_after_builders)
    api.assertions.assertCountEqual(expected_no_collect_builders,
                                    actual_no_collect_builders)


def GenTests(api):
  # Should categorize using CoverageRules.
  yield api.test(
      'cq',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(builder='cq-orchestrator'),
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='.*',
                          file_allowlist_regexps=['.*'],
                          branch_allowlist_regexps=['.*'],
                      ),
                  ]),
              'expected_collect_builders': ['target3-env'],
              'expected_collect_after_builders': ['target1-env'],
              'expected_no_collect_builders': ['target2-env'],
          }),
      api.step_data(
          'categorize builds by collect handling.get testable builders.test_plan get-testable',
          stdout=api.raw_io.output_text('target3-env target2-env')),
      api.post_check(
          post_process.MustRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cq-force-testable-builders',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(builder='cq-orchestrator'),
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='.*',
                          file_allowlist_regexps=['.*'],
                          branch_allowlist_regexps=['.*'],
                      ),
                  ]),
              'expected_collect_builders': ['target3-env', 'target1-env'],
              'expected_collect_after_builders': [],
              'expected_no_collect_builders': ['target2-env'],
          }),
      api.properties(
          **{
              '$chromeos/cros_cq_additional_tests': {
                  'enable_running_additional_tests': True,
                  'run_additional_tests_as_critical': False,
              }
          }),
      api.git_footers.simulated_get_footers([
          'target1'
      ], 'categorize builds by collect handling.get additional testable builders',
                                            2),
      api.step_data(
          'categorize builds by collect handling.get testable builders.test_plan get-testable',
          stdout=api.raw_io.output_text('target3-env target2-env')),
      api.post_check(
          post_process.MustRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  # Failure to categorize via CoverageRules default to collecting all
  # non-critical builds before end-to-end testing.
  yield api.test(
      'cq-get-testable-failure',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(builder='cq-orchestrator'),
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='.*',
                          file_allowlist_regexps=['.*'],
                          branch_allowlist_regexps=['.*'],
                      ),
                  ]),
              'expected_collect_builders': ['target1-env', 'target3-env'],
              'expected_collect_after_builders': [],
              'expected_no_collect_builders': ['target2-env'],
          }),
      api.step_data(
          'categorize builds by collect handling.get testable builders.test_plan get-testable',
          retcode=1),
      api.post_check(
          post_process.MustRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  # The rest of the test cases should use the default categorization using
  # ChildSpecs.
  yield api.test(
      'cq-v2-planning-not-enabled',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(builder='cq-orchestrator'),
      api.post_check(
          post_process.DoesNotRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cq-v1-planning-with-force-relevant-testable-builders',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.try_build(builder='cq-orchestrator'),
      api.properties(
          **{
              '$chromeos/cros_cq_additional_tests': {
                  'enable_running_additional_tests': True,
                  'run_additional_tests_as_critical': False,
              }
          }),
      api.properties(
          expected_collect_builders=['target3-env', 'target1-env'],
          expected_collect_after_builders=['target2-env'],
          expected_no_collect_builders=[],
      ),
      api.git_footers.simulated_get_footers([
          'target3'
      ], 'categorize builds by collect handling.get additional testable builders',
                                            2),
      api.post_check(
          post_process.DoesNotRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'non-cq',
      api.buildbucket.try_build(builder='postsubmit-orchestrator'),
      api.post_check(
          post_process.DoesNotRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )
