# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the get_requested_snapshot_builders function."""

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_modules.chromeos.looks_for_green.tests.test import GetRequestedSnapshotBuildersProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'looks_for_green',
]

PROPERTIES = GetRequestedSnapshotBuildersProperties


def RunSteps(api, properties):
  expected = properties.expected_requested_snapshot_builders or None

  result = api.looks_for_green.get_requested_snapshot_builders(
      properties.necessary_builders)

  api.assertions.assertEqual(expected, result)


def GenTests(api):
  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'snapshot-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1-snapshot'
  orch.orchestrator.child_specs.add().name = 'builder2-snapshot'
  orch.orchestrator.child_specs.add().name = 'builder4-snapshot'

  yield api.test(
      'basic',
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(necessary_builders=['builder1-cq'],
                     expected_requested_snapshot_builders=['builder1-snapshot'
                                                          ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'missing-snapshot-builder',
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(necessary_builders=['builder1-cq', 'missing-builder-cq'],
                     expected_requested_snapshot_builders=[]),
      api.post_process(post_process.DropExpectation),
  )
