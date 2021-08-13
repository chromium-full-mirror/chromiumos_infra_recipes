# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify module inherits some recipe properties.

Verify that merging BuildTargetProperties into BuildMenuProperties is
behaving as expected.
"""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
]

from google.protobuf.json_format import MessageToDict

from PB.recipe_modules.chromeos.build_menu.tests.properties import TestProperties
from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties
from PB.recipes.chromeos.build_target import BuildTargetProperties

PROPERTIES = TestProperties


def RunSteps(api, properties):
  actual = MessageToDict(
      BuildMenuProperties(
          build_target=api.build_menu.build_target,
          force_relevant_build=api.build_menu.force_relevant_build,
          artifact_build=api.build_menu.artifact_build),
      including_default_value_fields=True)
  expected = MessageToDict(properties.expected_properties,
                           including_default_value_fields=True)
  api.assertions.assertEqual(expected, actual)


def GenTests(api):

  def test_props(**kwargs):
    return api.properties(TestProperties(expected_properties=kwargs))

  default_target = dict(name='amd64-generic')
  build_target = dict(name='target')

  # Verify that the default properties from build_menu.test work.
  yield api.build_menu.test('basic', test_props(build_target=default_target))

  args = dict(build_target=build_target, force_relevant_build=True,
              artifact_build=True)

  yield api.build_menu.test('only-module', test_props(**args),
                            build_target=None,
                            input_properties={'$chromeos/build_menu': args})
