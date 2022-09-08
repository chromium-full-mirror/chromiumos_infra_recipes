# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import struct_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'build_plan',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  child_specs = api.cros_infra_config.get_builder_config(
      'postsubmit-orchestrator').orchestrator.child_specs
  completed_builds, existing_builds, new_requests = api.build_plan.get_build_plan(
      child_specs, True, [], common_pb2.GitilesCommit(),
      common_pb2.GitilesCommit())
  api.assertions.assertEqual(completed_builds, [])
  api.assertions.assertEqual(len(new_requests), 2)
  api.assertions.assertEqual(new_requests[0].builder.builder,
                             'arm-generic-postsubmit')
  api.assertions.assertEqual(len(existing_builds), 1)
  api.assertions.assertEqual(existing_builds[0].id, 8922054662172514003)


def GenTests(api):
  input_proto = api.build_plan.input_proto
  existing_annealing_builds = [
      build_pb2.Build(id=8922054662172514002,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.STARTED,
                      input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514003,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514005,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.SUCCESS,
                      input=dict(properties=struct_pb2.Struct())),  # no bt
      build_pb2.Build(id=8922054662172514004,
                      builder={'builder': 'amd64-generic-postsubmit'},
                      status=common_pb2.SCHEDULED,
                      input=input_proto(None, 'amd64-generic')),
  ]

  yield api.test(
      'basic',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='postsubmit-orchestrator'),
      api.buildbucket.simulated_search_results(
          existing_annealing_builds, 'get snapshot builds.buildbucket.search'))
