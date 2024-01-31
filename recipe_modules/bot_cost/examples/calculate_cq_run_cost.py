# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'cros_tags',
]



def RunSteps(api: RecipeApi):
  output = build_pb2.Build.Output()
  output.properties['build_cost'] = 10.0
  child_builds = [
      build_pb2.Build(id=124, output=output),
      build_pb2.Build(id=125),
  ]
  with api.bot_cost.cq_run_cost_context():
    with api.step.nest('calculate cq run cost') as test_step:
      cq_run_cost = api.bot_cost._calculate_cq_run_cost(child_builds, test_step)
      api.assertions.assertEqual(10.0, cq_run_cost)
      log = test_step.logs['child builds missing build_cost']
      api.assertions.assertEqual(['125'], log)


def GenTests(api: RecipeTestApi):
  orch_build = build_pb2.Build(id=123, status=common_pb2.STARTED,
                               start_time=timestamp_pb2.Timestamp(seconds=0),
                               update_time=timestamp_pb2.Timestamp(seconds=0))

  yield api.test(
      'basic', api.buildbucket.build(orch_build),
      api.buildbucket.simulated_get(
          orch_build, step_name='calculate cq run cost'
          '.calculate build cost.buildbucket.get'))
