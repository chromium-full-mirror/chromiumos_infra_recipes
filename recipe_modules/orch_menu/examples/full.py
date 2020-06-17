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

  def test(name, missing_ok=False, expect_missing_config=False,
           test_footers=None, **kwargs):
    """Helper for creating build.

    Args:
      name (str): Test name.
      expect_config_fail (bool): Whether to expect setup_orchestrator to fail.
      test_footers (str): git_footers test data.
    """
    kwargs.setdefault(
        'input_properties',
        OrchestratorProperties(
            update_manifest_refs=OrchestratorProperties.UpdateManifestRefs(
                start='refs/heads/postsubmit')))
    ret = api.test(
        name,
        api.test_util.test_orchestrator(**kwargs).build,
        api.properties(
            FullProperties(missing_ok=missing_ok,
                           expect_missing_config=expect_missing_config,
                           test_footers=test_footers)))
    return ret

  yield test('basic')

  yield test('two-footers', expect_missing_config=True,
             test_footers='foot1\nfoot2')

  yield test(
      'bad-ref', input_properties=OrchestratorProperties(
          update_manifest_refs=OrchestratorProperties.UpdateManifestRefs(
              start='missing-ref-heads')), missing_ok=True,
      expect_missing_config=True)

  yield test('required-missing-config', builder='no-config',
             expect_missing_config=True)

  yield test('forgiven-missing-builder', builder='no-config', missing_ok=True,
             expect_missing_config=True)
