# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_plan.examples.get_completed_builds import \
  GetCompletedBuildsProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_plan',
    'cros_history',
]


PROPERTIES = GetCompletedBuildsProperties


def RunSteps(api, properties):
  result = api.build_plan.get_completed_builds([
      BuilderConfig.Orchestrator.ChildSpec(name='atlas-cq'),
      BuilderConfig.Orchestrator.ChildSpec(name='amd64-generic-cq'),
  ], properties.forced_rebuilds)
  actual_completed_builders = [build.builder.builder for build in result]
  api.assertions.assertEqual(
      set(actual_completed_builders), set(properties.expected_completed))


def GenTests(api):
  input_proto = api.build_plan.input_proto
  builds = [
      build_pb2.Build(id=8922054662172514000,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514001,
                      builder={'builder': 'arm-generic-cq'},
                      status=common_pb2.STARTED,
                      input=input_proto(None, 'arm-generic')),
      build_pb2.Build(id=8922054662172514002, builder={'builder': 'atlas-cq'},
                      start_time=timestamp_pb2.Timestamp(seconds=1562475245),
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'atlas')),
  ]

  yield api.test(
      'one-failure-no-forced-rebuilds',
      api.buildbucket.simulated_search_results(
          builds, 'get completed builds.get change build history.'
          'buildbucket.search'),
      api.properties(**{
          'forced_rebuilds': [],
          'expected_completed': ['amd64-generic-cq']
      }))

  yield api.test(
      'one-failure-all-forced-rebuilds',
      api.buildbucket.simulated_search_results(
          builds, 'get completed builds.get change build history.'
          'buildbucket.search'),
      api.properties(**{
          'forced_rebuilds': ['all'],
          'expected_completed': []
      }))

  yield api.test(
      'one-failure-one-force-rebuild',
      api.buildbucket.simulated_search_results(
          builds, 'get completed builds.get change build history.'
          'buildbucket.search'),
      api.properties(**{
          'forced_rebuilds': ['amd64-generic-cq'],
          'expected_completed': []
      }))
