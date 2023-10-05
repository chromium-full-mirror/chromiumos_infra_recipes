# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import struct_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'build_plan',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  input_proto = api.build_plan.test_api.input_proto
  existing_annealing_builds = [
      build_pb2.Build(id=8922054662172514002,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.STARTED,
                      input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514003,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SUCCESS,
                      input=input_proto(None, 'amd64-generic')),
      build_pb2.Build(id=8922054662172514005,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SUCCESS,
                      input={'properties': struct_pb2.Struct()}),  # no bt
      build_pb2.Build(id=8922054662172514004,
                      builder={'builder': 'amd64-generic-cq'},
                      status=common_pb2.SCHEDULED,
                      input=input_proto(None, 'amd64-generic')),
  ]
  results = api.build_plan.prioritize_builds(existing_annealing_builds)
  api.assertions.assertEqual(len(results), 1)
  api.assertions.assertEqual(results[0].id, 8922054662172514003)


def GenTests(api):
  yield api.test('basic')
