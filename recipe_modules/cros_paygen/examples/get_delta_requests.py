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
    srcs = properties.signed_srcs
    tgts = properties.signed_tgts
  elif properties.request_type == GetRequestTestInputProperties.UNSIGNED:
    srcs = properties.unsigned_srcs
    tgts = properties.unsigned_tgts
  elif properties.request_type == GetRequestTestInputProperties.DLC:
    srcs = properties.dlc_srcs
    tgts = properties.dlc_tgts

  reqs = api.cros_paygen.get_delta_requests(payload_cfg, srcs, tgts, 'b', True,
                                            'mp-v2', False)

  api.assertions.assertEqual(len(properties.expected_reqs), len(reqs))
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)

  # Show that if generate_delta is false, there are no full deltas.
  payload_cfg['generate_delta'] = False
  no_reqs = api.cros_paygen.get_delta_requests(payload_cfg, srcs, tgts, 'b',
                                               True, 'mp-v2', False)
  api.assertions.assertEqual([], no_reqs)


def GenTests(api):
  yield api.test(
      'basic-signed',
      api.cros_paygen.props(api.properties,
                            GetRequestTestInputProperties.SIGNED,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_SIGNED,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-unsigned',
      api.cros_paygen.props(api.properties,
                            GetRequestTestInputProperties.UNSIGNED,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_UNSIGNED,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-payload',
      api.cros_paygen.props(api.properties, GetRequestTestInputProperties.DLC,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_DLC,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))

  # We doesn't check for dups, so adding one works for multiple.
  multi_src_props = deepcopy(api.cros_paygen.BASIC_TEST_PROPS)
  multi_src_props['signed_srcs'].append(api.cros_paygen.SIGNED_SRC)
  multi_src_props['signed_srcs'].append(api.cros_paygen.SIGNED_SRC_IRRELEVANT)
  yield api.test(
      'multiple-signed',
      api.cros_paygen.props(
          api.properties, GetRequestTestInputProperties.SIGNED,
          api.cros_paygen.EXAMPLE_GEN_REQUEST_DELTA_SIGNED * 2,
          **multi_src_props), api.post_check(post_process.StatusSuccess))
