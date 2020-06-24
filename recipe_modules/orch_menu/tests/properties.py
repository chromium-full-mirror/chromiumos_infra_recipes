# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify module inherits some recipe properties.

Verify that merging OrchestratorProperties into OrchMenuProperties is
behaving as expected.
"""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'orch_menu',
]

from google.protobuf.json_format import MessageToDict

from PB.recipe_modules.chromeos.orch_menu.tests.properties import TestProperties
from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties
from PB.recipes.chromeos.orchestrator import OrchestratorProperties

PROPERTIES = TestProperties


def RunSteps(api, properties):
  actual = MessageToDict(api.orch_menu._properties)
  expected = MessageToDict(properties.expected_properties)
  api.assertions.assertEqual(expected, actual)


def GenTests(api):

  def test_props(cq=False, **kwargs):
    props = api.orch_menu.get_default_module_properties(cq=cq)
    props.update(**kwargs)
    return api.properties(TestProperties(expected_properties=props))

  recipe_refs = OrchestratorProperties.UpdateManifestRefs(
      start='refs/heads/postsubmit')
  module_refs = OrchMenuProperties.UpdateManifestRefs(
      start='refs/heads/postsubmit')

  # Verify that the default properties from orch_menu.test work for cq=False.
  yield api.orch_menu.test('basic-postsubmit',
                           test_props(update_manifest_refs=module_refs))

  # Verify that the default properties from orch_menu.test work for cq=True.
  yield api.orch_menu.test('basic-cq', test_props(cq=True), cq=True)

  yield api.orch_menu.test(
      'only-recipe',
      test_props(update_manifest_refs=module_refs,
                 stagger_children_seconds=4.0),
      input_properties=OrchestratorProperties(update_manifest_refs=recipe_refs,
                                              stagger_children_seconds=4.0))

  yield api.orch_menu.test(
      'only-module',
      test_props(update_manifest_refs=module_refs,
                 stagger_children_seconds=4.0), input_properties={
                     '$chromeos/orch_menu':
                         dict(
                             update_manifest_refs=MessageToDict(module_refs),
                             stagger_children_seconds=4.0)
                 })
