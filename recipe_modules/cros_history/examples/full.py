# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
    'input_patches': Property(default=[]),
    'output_builds': Property(default=[]),
}


def RunSteps(api, input_patches, output_builds):
  previous_builds = (api.cros_history.passed_builds(input_patches))
  api.assertions.assertEqual(previous_builds, output_builds)


def GenTests(api):
  yield api.test('without_patches')

  yield (api.test('patch_without_history') +
         api.buildbucket.simulated_search_results(
             [], 'Looking for successful builds.buildbucket.search') +
         api.properties(input_patches=[
             common_pb2.GerritChange(change=1234),
             common_pb2.GerritChange(change=2341)
         ]))

  yield (
      api.test('patch_with_history') +
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, builder=build_pb2.BuilderID(builder='betty')),
          build_pb2.Build(id=231, builder=build_pb2.BuilderID(builder='reef'))
      ], 'Looking for successful builds.buildbucket.search') +
      api.properties(input_patches=[common_pb2.GerritChange(change=2341)]) +
      api.properties(output_builds=[
          build_pb2.Build(id=123, builder=build_pb2.BuilderID(builder='betty')),
          build_pb2.Build(id=231, builder=build_pb2.BuilderID(builder='reef'))
      ]))
