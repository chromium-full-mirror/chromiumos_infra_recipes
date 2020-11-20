# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_paygen.examples.test import GetRequestTestInputProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_paygen',
]

PROPERTIES = GetRequestTestInputProperties


def RunSteps(api, properties):
  reqs = api.cros_paygen.get_n2n_requests(properties.unsigned_tgts, 'b', True,
                                          True)
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)


def GenTests(api):
  yield api.test(
      'basic',
      api.cros_paygen.props(api.properties,
                            GetRequestTestInputProperties.UNSIGNED,
                            api.cros_paygen.EXAMPLE_GEN_REQUEST_N2N,
                            **api.cros_paygen.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))
