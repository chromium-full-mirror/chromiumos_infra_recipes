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
  with api.step.nest('terminal build') as test_step:
    build_cost = api.bot_cost.calculate_build_cost(123, 'small')
    api.assertions.assertNotEqual(0, build_cost)
  with api.step.nest('started build') as test_step:
    build_cost = api.bot_cost.calculate_build_cost(123, 'small')
    api.assertions.assertNotEqual(0, build_cost)
  with api.step.nest('scheduled build') as test_step:
    build_cost = api.bot_cost.calculate_build_cost(123, 'small')
    api.assertions.assertEqual(0, build_cost)


def GenTests(api):
  terminal_build = build_pb2.Build(
      id=123, status=common_pb2.SUCCESS,
      start_time=timestamp_pb2.Timestamp(seconds=5000),
      end_time=timestamp_pb2.Timestamp(seconds=15000))

  started_build = build_pb2.Build(
      id=123, status=common_pb2.STARTED,
      start_time=timestamp_pb2.Timestamp(seconds=5000),
      update_time=timestamp_pb2.Timestamp(seconds=15000))

  scheduled_build = build_pb2.Build(
      id=123, status=common_pb2.SCHEDULED,
      start_time=timestamp_pb2.Timestamp(seconds=5000),
      update_time=timestamp_pb2.Timestamp(seconds=15000),
      end_time=timestamp_pb2.Timestamp(seconds=15000))

  yield (api.test('basic') + api.buildbucket.simulated_get(
      terminal_build, step_name='terminal build.buildbucket.get') +
         api.buildbucket.simulated_get(
             started_build, step_name='started build.buildbucket.get') +
         api.buildbucket.simulated_get(
             scheduled_build, step_name='scheduled build.buildbucket.get'))
