# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.build_plan.build_plan import BuildPlanProperties
from PB.recipe_modules.chromeos.orch_menu.tests.collect import CollectProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'orch_menu',
    'test_util',
]

PROPERTIES = CollectProperties


def RunSteps(api, properties):
  build = api.buildbucket.build
  child_specs_dict = {}
  child_targets_dict = {}
  forced_testable_builders = properties.forced_testable_builders
  if properties.child_spec.name:
    child_specs_dict[build.builder.builder] = properties.child_spec
  if properties.child_target.name:
    child_targets_dict[properties.build_target.name] = properties.child_target
  # pylint: disable=protected-access
  api.assertions.assertEqual(
      properties.expected_collect,
      api.orch_menu._collect_value(build, child_specs_dict, child_targets_dict,
                                   forced_testable_builders))


def GenTests(api):

  ChildSpec = BuilderConfig.Orchestrator.ChildSpec
  CollectHandling = ChildSpec.CollectHandling
  build_target = 'amd64-generic'
  builders = ['%s-postsubmit' % build_target, '%s-slim-cq' % build_target]

  # Iterate through all of the possible cases for builder, child_specs_dict, and
  # child_targets_dict, and verify that we get the right answer each time.
  for builder in builders:
    for spec_name, spec_value in CollectHandling.items():
      for target_name, target_value in CollectHandling.items():
        if spec_value:
          expected_collect = spec_value
        elif target_value:
          expected_collect = target_value
        else:
          expected_collect = ChildSpec.COLLECT
        properties = CollectProperties(expected_collect=expected_collect)
        if spec_value:
          properties.child_spec.name = builder
          properties.child_spec.collect_handling = spec_value
        if target_value:
          properties.child_target.name = build_target
          properties.child_target.collect_handling = target_value

        yield api.orch_menu.test(
            '%s-%s-%s' % (builder, spec_name, target_name),
            api.test_util.test_child_build(build_target, builder=builder).build,
            api.properties(properties),
            api.post_process(post_process.DropExpectation),
        )

  yield api.orch_menu.test(
      'additional-chrome-pupr-builders',
      api.test_util.test_child_build(build_target,
                                     builder=f'{build_target}-cq').build,
      api.properties(
          CollectProperties(expected_collect=ChildSpec.NO_COLLECT), **{
              '$chromeos/build_plan':
                  BuildPlanProperties(
                      additional_chrome_pupr_builders=['amd64-generic-cq'],
                  ),
          }),
      api.post_process(post_process.DropExpectation),
  )
