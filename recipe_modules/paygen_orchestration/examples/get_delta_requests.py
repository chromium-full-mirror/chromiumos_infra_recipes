# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json
from copy import deepcopy

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
  payload_cfg = json.loads(properties.payload_cfg)

  if properties.request_type == GetRequestTestInputProperties.SIGNED:
    srcs = properties.signed_srcs
    tgts = properties.signed_tgts
  elif properties.request_type == GetRequestTestInputProperties.UNSIGNED:
    srcs = properties.unsigned_srcs
    tgts = properties.unsigned_tgts
  elif properties.request_type == GetRequestTestInputProperties.DLC:
    srcs = properties.dlc_srcs
    tgts = properties.dlc_tgts

  reqs = api.paygen_orchestration.get_delta_requests(payload_cfg, srcs, tgts,
                                                     'b', True, False,
                                                     minios=minios)

  api.assertions.assertEqual(len(properties.expected_reqs), len(reqs))
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)

  # Show that if generate_delta is false, there are no full deltas.
  payload_cfg['generate_delta'] = False
  no_reqs = api.paygen_orchestration.get_delta_requests(payload_cfg, srcs, tgts,
                                                        'b', True, False,
                                                        minios=minios)
  api.assertions.assertEqual([], no_reqs)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic-signed',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.SIGNED,
          api.paygen_orchestration.get_example_gen_requests_delta_signed(),
          **api.paygen_orchestration.BASIC_TEST_PROPS),
  )

  yield api.test(
      'basic-signed-no-minios',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.SIGNED,
          api.paygen_orchestration.get_example_gen_requests_delta_signed(
              minios=False), no_minios=True,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
  )

  yield api.test(
      'basic-unsigned',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.UNSIGNED,
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
  )

  yield api.test(
      'basic-payload',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.DLC,
          api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
  )

  # We doesn't check for dups, so adding one works for multiple.
  multi_src_props = deepcopy(api.paygen_orchestration.BASIC_TEST_PROPS)
  multi_src_props['signed_srcs'].append(api.paygen_orchestration.SIGNED_SRC)
  multi_src_props['signed_srcs'].append(
      api.paygen_orchestration.SIGNED_SRC_IRRELEVANT)
  yield api.test(
      'multiple-signed',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.SIGNED,
          api.paygen_orchestration.get_example_gen_requests_delta_signed() * 2,
          **multi_src_props),
  )
