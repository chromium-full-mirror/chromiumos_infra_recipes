# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic examples of CrOS snapshot information manipulation."""

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_snapshot.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_snapshot',
    'cros_infra_config',
    'git_footers',
]

PROPERTIES = TestInputProperties


def RunSteps(api, properties: TestInputProperties):
  api.cros_infra_config.configure_builder()

  if properties.HasField('expected_snapshot_identifier'):
    api.assertions.assertEqual(
        properties.expected_snapshot_identifier,
        api.cros_snapshot.snapshot_identifier(test_value='1234567'))
  if properties.HasField('expected_is_snapshot_build'):
    api.assertions.assertEqual(properties.expected_is_snapshot_build,
                               api.cros_snapshot.is_snapshot_build())


def GenTests(api):
  snapshot_config = BuilderConfig()
  snapshot_config.id.type = BuilderConfig.Id.SNAPSHOT
  non_snapshot_config = BuilderConfig()
  non_snapshot_config.id.type = BuilderConfig.Id.TYPE_UNSPECIFIED

  yield api.test(
      'basic',
      api.cros_infra_config.use_custom_builder_config(
          snapshot_config, step_name='configure builder'),
      api.properties(
          TestInputProperties(
              expected_snapshot_identifier='1234567',
              expected_is_snapshot_build=True,
          )))

  # Non snapshot build on non-snapshot change
  yield api.test(
      'non-snapshot',
      api.cros_infra_config.use_custom_builder_config(
          non_snapshot_config, step_name='configure builder'),
      api.git_footers.simulated_get_footers([], 'read snapshot identifier'),
      api.properties(
          TestInputProperties(
              expected_snapshot_identifier='',
              expected_is_snapshot_build=False,
          )))

  # Non snapshot build on snapshot change
  yield api.test(
      'non-snapshot-on-snapshot-commit',
      api.cros_infra_config.use_custom_builder_config(
          non_snapshot_config, step_name='configure builder'),
      api.properties(
          TestInputProperties(
              expected_snapshot_identifier='1234567',
              expected_is_snapshot_build=False,
          )))

  yield api.test(
      'another-snapshot-identifier',
      api.git_footers.simulated_get_footers(['9999999'],
                                            'read snapshot identifier'),
      api.properties(
          TestInputProperties(
              expected_snapshot_identifier='9999999',
          )))

  # Non snapshot commit
  yield api.test(
      'no-snapshot-identifier',
      api.git_footers.simulated_get_footers([], 'read snapshot identifier'),
      api.properties(TestInputProperties(expected_snapshot_identifier='')))
