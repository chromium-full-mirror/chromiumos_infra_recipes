# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'orch_menu',
    'test_util',
]

from PB.recipe_modules.chromeos.orch_menu.examples.full import FullProperties
from PB.recipes.chromeos.orchestrator import OrchestratorProperties

PROPERTIES = FullProperties


def RunSteps(api, properties):
  with api.orch_menu.setup_orchestrator(
      missing_ok=properties.missing_ok,
      test_footers=properties.test_footers) as config:
    api.assertions.assertEqual(config, api.orch_menu.config)
    if not config:
      api.assertions.assertTrue(properties.expect_missing_config)
      return
    api.assertions.assertIsNotNone(config)

    api.assertions.assertEqual(
        str(api.buildbucket.build.input.gerrit_changes),
        str(api.orch_menu.gerrit_changes))

    api.orch_menu.push_manifest_refs('refs/heads/postsubmit')


def GenTests(api):

  yield api.orch_menu.test('basic')

  yield api.orch_menu.test(
      'two-footers',
      api.properties(
          FullProperties(expect_missing_config=True,
                         test_footers='foot1\nfoot2')))

  yield api.orch_menu.test(
      'bad-ref',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      input_properties=OrchestratorProperties(
          update_manifest_refs=OrchestratorProperties.UpdateManifestRefs(
              start='missing-ref-heads')))

  yield api.orch_menu.test(
      'required-missing-config',
      api.properties(FullProperties(expect_missing_config=True)),
      builder='no-config')

  yield api.orch_menu.test(
      'forgiven-missing-config',
      api.properties(
          FullProperties(missing_ok=True, expect_missing_config=True)),
      builder='no-config')
