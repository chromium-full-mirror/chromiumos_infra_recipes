# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.paygen_orchestration.examples.test import GetRequestTestInputProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GetRequestTestInputProperties


def RunSteps(api: RecipeApi, properties: GetRequestTestInputProperties):
  if properties.request_type == GetRequestTestInputProperties.SIGNED:
    tgts = properties.signed_tgts
  elif properties.request_type == GetRequestTestInputProperties.UNSIGNED:
    tgts = properties.unsigned_tgts
  elif properties.request_type == GetRequestTestInputProperties.DLC:
    tgts = properties.dlc_tgts

  reqs = api.paygen_orchestration.get_full_requests(tgts, 'b', True, True)

  api.assertions.assertEqual(len(properties.expected_reqs), len(reqs))
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic-signed',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.SIGNED,
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_FULL_SIGNED,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-unsigned',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.UNSIGNED,
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-payload',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.DLC,
          api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))
