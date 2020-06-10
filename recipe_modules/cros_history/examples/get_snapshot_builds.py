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
    'test_util',
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

  def build(build_id, builder, build_target):
    ret = build_pb2.Build(id=build_id,
                          builder=build_pb2.BuilderID(builder=builder))
    ret.input.properties.update(
        api.test_util.build_target_properties(build_target_name=build_target))
    return ret

  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results([
          build(123, 'eve-snapshot', 'eve'),
          build(231, 'bob-snapshot', 'bob'),
          build(312, 'cq-orchestrator', None)
      ], 'get snapshot builds.buildbucket.search'))
