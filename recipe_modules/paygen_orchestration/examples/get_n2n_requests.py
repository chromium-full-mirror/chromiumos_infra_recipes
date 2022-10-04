# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.paygen_orchestration.examples.test import GetRequestTestInputProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GetRequestTestInputProperties


def RunSteps(api, properties):
  reqs = api.paygen_orchestration.get_n2n_requests(properties.unsigned_tgts,
                                                   'b', True, False)
  for x, y in zip(properties.expected_reqs, reqs):
    api.assertions.assertEqual(x, y)


def GenTests(api):
  yield api.test(
      'basic',
      api.paygen_orchestration.props(
          api.properties, GetRequestTestInputProperties.UNSIGNED,
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_N2N,
          **api.paygen_orchestration.BASIC_TEST_PROPS),
      api.post_check(post_process.StatusSuccess))
