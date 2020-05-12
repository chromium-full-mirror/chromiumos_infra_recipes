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
  fake_builder = build_pb2.BuilderID(builder='bojack-cq', bucket='cq',
                                     project='chromeos')
  example_build = build_pb2.Build(id=1234, builder=fake_builder,
                                  status=common_pb2.STARTED)
  previous_builds = api.cros_history.get_matching_builds(
      example_build, statuses=[common_pb2.STARTED], start_build_id=0123)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results(
          [build_pb2.Build()], 'find matching builds.buildbucket.search'),
  )
