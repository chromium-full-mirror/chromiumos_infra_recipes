# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfig

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'git_footers',
    'snapshot_orch_menu',
    'test_util',
]


def RunSteps(api):
  with api.snapshot_orch_menu.setup_orchestrator():
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
    collect_when_dict = api.snapshot_orch_menu.categorize_builds_by_collect_handling(
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
  yield api.test(
      'postsubmit',
      api.buildbucket.try_build(builder='postsubmit-orchestrator'),
      api.post_check(
          post_process.DoesNotRun,
          'categorize builds by collect handling.get testable builders'),
      api.post_process(post_process.DropExpectation),
  )
