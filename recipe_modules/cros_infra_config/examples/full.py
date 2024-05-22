# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_modules.chromeos.cros_infra_config.examples.full import FullProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]


PROPERTIES = FullProperties


def RunSteps(api, properties):
  builder = api.buildbucket.build.builder.builder
  builder_config = api.cros_infra_config.get_builder_config(builder)
  api.cros_infra_config.force_reload()
  api.cros_infra_config.safe_get_builder_configs([builder])

  api.assertions.assertEqual(builder_config.id.name, builder)

  # Verify that the jsonpb was parsed.
  child_specs = builder_config.orchestrator.child_specs
  api.assertions.assertEqual(len(child_specs), len(properties.children_names))
  api.assertions.assertEqual([x.name for x in child_specs],
                             properties.children_names)

  _ = api.cros_infra_config.experiments_for_child_build


def GenTests(api):
  yield api.test(
      'basic',
      api.test_util.test_orchestrator(builder='snapshot-orchestrator').build,
      api.properties(
          FullProperties(children_names=[
              'amd64-generic-snapshot',
              'arm-generic-snapshot',
              'grunt-snapshot',
          ])))

  # Verify that override_builder_configs_test_data works.
  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'snapshot-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1'
  yield api.test(
      'forced-config',
      api.test_util.test_orchestrator(builder='snapshot-orchestrator').build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(FullProperties(children_names=['builder1'])),
  )
