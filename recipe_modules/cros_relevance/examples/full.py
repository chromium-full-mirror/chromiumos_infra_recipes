# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'cros_relevance',
]


def RunSteps(api):
  result = api.cros_relevance.is_build_pointless(build_pb2.Build())

def GenTests(api):
  builder = 'builder'
  build_config = [dict(build_target='build_target')]
  yield (api.test('basic') +
        api.cros_relevance.simulate_run_pointless_build_checker())
