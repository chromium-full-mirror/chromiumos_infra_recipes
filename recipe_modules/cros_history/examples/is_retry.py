# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]

PROPERTIES = {'is_retry': Property(default=False)}


def RunSteps(api, is_retry):
  api.assertions.assertEqual(
      api.cros_history.is_retry(api.buildbucket.build), is_retry)


def GenTests(api):

  yield api.test('basic')

  yield api.test(
      'is-retry',
      api.buildbucket.simulated_search_results([
          api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                           builder='bojack-cq',
                                           status='SUCCESS', build_id=123)
      ], 'find matching builds.buildbucket.search'),
      api.properties(is_retry=True))

  yield api.test('test-value', api.cros_history.is_retry(True),
                 api.properties(is_retry=True))
