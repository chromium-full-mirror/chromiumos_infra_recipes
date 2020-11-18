# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from copy import deepcopy
import json

from PB.recipe_modules.chromeos.cros_paygen.examples.test import GetRequestTestInputProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_paygen',
]

PROPERTIES = GetRequestTestInputProperties


def RunSteps(api, properties):
  payload_cfg = json.loads(properties.payload_cfg)

  if properties.request_type == GetRequestTestInputProperties.SIGNED:
    tgts = properties.signed_tgts
  elif properties.request_type == GetRequestTestInputProperties.UNSIGNED:
    tgts = properties.unsigned_tgts
  elif properties.request_type == GetRequestTestInputProperties.DLC:
    tgts = properties.dlc_tgts

  reqs = api.cros_paygen.get_full_requests(tgts, 'b', True, 'mp-v2', True)

  api.assertions.assertEqual(len(properties.expected_reqs), len(reqs))
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)


def GenTests(api):
  yield api.test(
      'basic-signed',
      api.cros_paygen.props(api.properties,
                            GetRequestTestInputProperties.SIGNED,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_FULL_SIGNED,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-unsigned',
      api.cros_paygen.props(api.properties,
                            GetRequestTestInputProperties.UNSIGNED,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_FULL_UNSIGNED,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-payload',
      api.cros_paygen.props(api.properties, GetRequestTestInputProperties.DLC,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_FULL_DLC,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))
