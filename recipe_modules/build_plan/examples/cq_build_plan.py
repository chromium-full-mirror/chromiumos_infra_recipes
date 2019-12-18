# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'build_plan',
    'cros_infra_config',
]


def RunSteps(api):
  child_builders = api.cros_infra_config.get_builder_config(
      'cq-orchestrator').orchestrator.children
  completed_builds, existing_builds, new_requests = api.build_plan.get_build_plan(
      child_builders, True, [common_pb2.GerritChange(change=1234)],
      common_pb2.GitilesCommit())
  api.assertions.assertEqual(existing_builds, [])
  api.assertions.assertEqual(len(completed_builds), 1)
  api.assertions.assertEqual(completed_builds[0].builder.builder,
                             'amd64-generic-cq')
  api.assertions.assertEqual(len(new_requests), 1)
  api.assertions.assertEqual(new_requests[0].builder.builder, 'atlas-cq')


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

  def cq_orchestrator_build_with_gerrit_change():
    """Generate a test build proto with no gitiles commit project."""
    build = api.buildbucket.ci_build_message(project='chromeos', bucket='cq',
                                             builder='cq-orchestrator')
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return api.buildbucket.build(build)

  yield (api.test('basic') + cq_orchestrator_build_with_gerrit_change() +
         api.buildbucket.simulated_search_results(
             builds, 'get build history.get completed builds.'
             'get change build history.buildbucket.search') +
         api.buildbucket.simulated_search_results(
             builds, 'get build history.find matching builds.'
             'buildbucket.search'))
