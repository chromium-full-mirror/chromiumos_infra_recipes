# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from copy import deepcopy
import json
from google.protobuf.json_format import MessageToJson

from PB.chromite.api.payload import GenerationRequest as GenerationRequest_pb2
from PB.recipe_modules.chromeos.cros_paygen.examples.test import GetRequestTestInputProperties

from recipe_engine import post_process

DEPS = ['recipe_engine/assertions', 'recipe_engine/properties', 'cros_paygen']

PROPERTIES = GetRequestTestInputProperties


def RunSteps(api, properties):
  if properties.request_type == GetRequestTestInputProperties.SIGNED:
    srcs = properties.signed_srcs
    tgts = properties.signed_tgts
  elif properties.request_type == GetRequestTestInputProperties.UNSIGNED:
    srcs = properties.unsigned_srcs
    tgts = properties.unsigned_tgts

  reqs = api.cros_paygen.get_requests(properties.cfg, srcs, tgts, 'b', True,
                                      'mp-v2', True)

  api.assertions.assertEqual(len(properties.expected_reqs), len(reqs))
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)

  # TODO(crbug.com/114859): Impl tests for dlc and full request.
  api.cros_paygen.get_full_requests()
  api.cros_paygen.get_dlc_requests()


def GenTests(api):
  basic_test_props = {
      'cfg': api.cros_paygen.EXAMPLE_SINGLE_PAYGEN_CONFIG,
      'signed_srcs': [api.cros_paygen.SIGNED_SRC],
      'signed_tgts': [api.cros_paygen.SIGNED_TGT],
      'unsigned_srcs': [api.cros_paygen.UNSIGNED_SRC],
      'unsigned_tgts': [api.cros_paygen.UNSIGNED_TGT],
      'full_update': False,
  }

  def props(request_type, expected_reqs, **kwargs):
    """Define a test prop from a request_type and incoming kwargs."""
    return api.properties(
        GetRequestTestInputProperties(request_type=request_type,
                                      cfg=kwargs['cfg'],
                                      signed_srcs=kwargs['signed_srcs'],
                                      signed_tgts=kwargs['signed_tgts'],
                                      unsigned_srcs=kwargs['unsigned_srcs'],
                                      unsigned_tgts=kwargs['unsigned_tgts'],
                                      full_update=kwargs['full_update'],
                                      expected_reqs=expected_reqs))

  yield api.test(
      'basic-signed',
      props(GetRequestTestInputProperties.SIGNED,
            api.cros_paygen.EXAMPLE_GEN_REQUEST_SIGNED, **basic_test_props),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'basic-unsigned',
      props(GetRequestTestInputProperties.UNSIGNED,
            api.cros_paygen.EXAMPLE_GEN_REQUEST_UNSIGNED, **basic_test_props),
      api.post_check(post_process.StatusSuccess))

  # It doesn't check for dups, so adding one works for multiple.
  multi_src_props = deepcopy(basic_test_props)
  multi_src_props['signed_srcs'].append(api.cros_paygen.SIGNED_SRC)
  multi_src_props['signed_srcs'].append(api.cros_paygen.SIGNED_SRC_IRRELEVANT)
  yield api.test(
      'multiple-signed',
      props(GetRequestTestInputProperties.SIGNED,
            api.cros_paygen.EXAMPLE_GEN_REQUEST_SIGNED * 2, **multi_src_props),
      api.post_check(post_process.StatusSuccess))
