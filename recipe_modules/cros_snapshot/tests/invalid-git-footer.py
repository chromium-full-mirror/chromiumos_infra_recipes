# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic examples of CrOS snapshot information manipulation."""

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

  api.assertions.assertEqual(properties.expected_snapshot_identifier,
                             api.cros_snapshot.snapshot_identifier())


def GenTests(api):
  # Invalid footer
  yield api.test(
      'multiple-snapshot-identifier',
      api.git_footers.simulated_get_footers(['1111', '2222', '3333'],
                                            'read snapshot identifier'),
      status='FAILURE')
