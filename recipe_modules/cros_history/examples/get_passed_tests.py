# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_history',
]


def RunSteps(api):
  api.assertions.assertItemsEqual(api.cros_history.get_passed_tests(),
                                  ['nami/hw/bvt-cq'])


def GenTests(api):
  yield api.test(
      'has-passed-tests',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_passed_tests(['nami/hw/bvt-cq'])],
          'get change test history.find matching builds.buildbucket.search'))
