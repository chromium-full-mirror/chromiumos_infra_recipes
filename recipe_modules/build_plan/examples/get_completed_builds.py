# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from PB.chromiumos.builder_config import BuilderConfig

from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'build_plan',
]


def RunSteps(api):
  result = api.build_plan.get_completed_builds([
      BuilderConfig.Orchestrator.ChildSpec(name = 'atlas-cq'),
      BuilderConfig.Orchestrator.ChildSpec(name = 'amd64-generic-cq'),
  ])
  api.assertions.assertEqual(len(result), 1)
  api.assertions.assertEqual(result[0].builder.builder, 'amd64-generic-cq')


def GenTests(api):
  input_proto = api.build_plan.input_proto
  builds = [
      build_pb2.Build(id=8922054662172514000, builder={
          'builder': 'amd64-generic-cq'
      }, status=common_pb2.SUCCESS, input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514001, builder={
          'builder': 'arm-generic-cq'
      }, status=common_pb2.STARTED, input=input_proto(None, 'arm-generic')),
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS, input=input_proto(
                          None, 'atlas')),
  ]

  yield (
      api.test('completed_builds') + api.buildbucket.simulated_search_results(
          builds, 'get completed builds.get change build history.'
          'buildbucket.search'))
