# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.paygen_orchestration.examples.test import GetRequestTestInputProperties

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'paygen_orchestration',
]


PROPERTIES = GetRequestTestInputProperties


def RunSteps(api: RecipeApi, properties: GetRequestTestInputProperties):
  minios = not properties.no_minios
  reqs = api.paygen_orchestration.get_n2n_requests(properties.unsigned_tgts,
                                                   'b', True, False,
                                                   minios=minios)
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.UNSIGNED,
          api.paygen_orchestration.get_example_gen_requests_delta_n2n(),
          **api.paygen_orchestration.BASIC_TEST_PROPS),
  )

  yield api.test(
      'no-minios',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.UNSIGNED,
          api.paygen_orchestration.get_example_gen_requests_delta_n2n(
              minios=False), no_minios=True,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
  )
