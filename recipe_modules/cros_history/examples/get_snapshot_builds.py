# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_history',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  expected = ['eve-snapshot', 'bob-snapshot']
  snapshot = common_pb2.GitilesCommit()
  result = api.cros_history.get_snapshot_builds(
      snapshot, ['eve-snapshot', 'winky-snapshot', 'bob-snapshot'],
      common_pb2.STATUS_UNSPECIFIED)
  build_targets = api.cros_infra_config.build_target_dict(result)
  result_builders = [build.builder.builder for build in result]
  api.assertions.assertCountEqual(build_targets.keys(), ['bob', 'eve'])
  api.assertions.assertEqual(result_builders, expected)


def GenTests(api):

  def build(build_id, builder, build_target=None):
    ret = build_pb2.Build(id=build_id,
                          builder=builder_common_pb2.BuilderID(builder=builder))
    if build_target:
      ret.input.properties.update(
          api.test_util.build_menu_properties(build_target_name=build_target))
    return ret

  yield api.test(
      'basic',
      api.buildbucket.simulated_multi_predicates_search_results([
          build(123, 'eve-snapshot', 'eve'),
          build(231, 'bob-snapshot', 'bob'),
          build(312, 'cq-orchestrator', None)
      ], 'get snapshot builds.buildbucket.search'))
