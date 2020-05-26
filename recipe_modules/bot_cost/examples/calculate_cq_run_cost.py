# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import timestamp_pb2


def RunSteps(api):
  output = build_pb2.Build.Output()
  output.properties['build_cost'] = 10.0
  tags = api.buildbucket.tags(
      parent_buildbucket_id=str(api.buildbucket.build.id))
  child_builds = [
      build_pb2.Build(id=124, tags=tags, output=output),
      build_pb2.Build(id=125, tags=tags),
      build_pb2.Build(id=126, output=output,
                      tags=api.buildbucket.tags(parent_buildbucket_id='122'))
  ]
  with api.step.nest('calculate cq run cost') as test_step:
    cq_run_cost = api.bot_cost._calculate_cq_run_cost(child_builds, test_step)
    api.assertions.assertEqual(10.0, cq_run_cost)
    log = test_step.logs['child builds missing build_cost']
    api.assertions.assertEqual(['125'], log)

  api.bot_cost.set_cq_run_cost(child_builds)


def GenTests(api):
  orch_build = build_pb2.Build(id=123, status=common_pb2.STARTED,
                               start_time=timestamp_pb2.Timestamp(seconds=0),
                               update_time=timestamp_pb2.Timestamp(seconds=0))
  orch_build.infra.swarming.bot_dimensions.extend(
      [common_pb2.StringPair(key='bot_size', value='small')])

  yield api.test('basic', api.buildbucket.build(orch_build))
