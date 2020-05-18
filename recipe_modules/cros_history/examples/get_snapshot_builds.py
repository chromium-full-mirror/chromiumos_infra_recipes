# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import struct_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_history',
]


def RunSteps(api):
  expected = ['eve-snapshot', 'bob-snapshot']
  snapshot = common_pb2.GitilesCommit()
  result = api.cros_history.get_snapshot_builds(
      snapshot, ['eve-snapshot', 'winky-snapshot', 'bob-snapshot'],
      common_pb2.STATUS_UNSPECIFIED)
  build_targets = api.cros_history.build_target_dict(result)
  result_builders = [build.builder.builder for build in result]
  api.assertions.assertItemsEqual(build_targets.keys(), ['bob', 'eve'])
  api.assertions.assertEqual(result_builders, expected)


def GenTests(api):
  build_targets = ['bob', 'eve']
  build_target_props = {
      bt: api.cros_history.build_target_property(bt) for bt in build_targets
  }

  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123,
                          builder=build_pb2.BuilderID(builder='eve-snapshot'),
                          input=dict(properties=build_target_props['eve'])),
          build_pb2.Build(id=231,
                          builder=build_pb2.BuilderID(builder='bob-snapshot'),
                          input=dict(properties=build_target_props['bob'])),
          build_pb2.Build(
              id=312, builder=build_pb2.BuilderID(builder='cq-orchestrator')),
      ], 'get snapshot builds.buildbucket.search'))
