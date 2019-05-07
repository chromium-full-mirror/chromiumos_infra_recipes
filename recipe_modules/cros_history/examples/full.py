# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import struct_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]

from PB.recipe_modules.chromeos.cros_history.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  # Tests for get_build_target.
  api.assertions.assertEqual(
      api.cros_history.get_build_target(build_pb2.Build()), None)
  api.assertions.assertEqual(
      api.cros_history.get_build_target(
          build_pb2.Build(input=build_pb2.Build.Input())), None)
  fake_target_struct = struct_pb2.Struct(
      fields={'name': struct_pb2.Value(string_value='fakey')})
  fake_input_properties = struct_pb2.Struct(fields={
      'build_target': struct_pb2.Value(struct_value=fake_target_struct)
  })
  fake_input = build_pb2.Build.Input(properties=fake_input_properties)
  api.assertions.assertEqual(
      api.cros_history.get_build_target(build_pb2.Build(input=fake_input)),
      'fakey')

  # Tests for passed_builds and passed_targets.
  api.assertions.assertEqual(api.cros_history.passed_builds([]), [])
  api.assertions.assertEqual(api.cros_history.passed_targets([]), set())
  if properties.input_build_patches:
    previous_builds = api.cros_history.passed_builds(
        properties.input_build_patches)
    api.assertions.assertItemsEqual(previous_builds, properties.output_builds)
  if properties.input_target_patches:
    previous_targets = api.cros_history.passed_targets(
        properties.input_target_patches)
    api.assertions.assertItemsEqual(
        list(previous_targets), properties.output_targets)


def GenTests(api):
  yield (
      api.test('patch_without_history') +
      api.buildbucket.simulated_search_results(
          [], 'Looking for successful builds (2).buildbucket.search') +
      api.properties(
          TestInputProperties(input_build_patches=[
              common_pb2.GerritChange(change=1234),
          ])) + api.properties(
              TestInputProperties(
                  input_target_patches=[common_pb2.GerritChange(change=2341)])))

  yield (
      api.test('passed_builds_with_history') +
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, builder=build_pb2.BuilderID(builder='betty')),
          build_pb2.Build(id=231, builder=build_pb2.BuilderID(builder='reef'))
      ], 'Looking for successful builds (2).buildbucket.search') +
      api.properties(
          TestInputProperties(
              input_build_patches=[common_pb2.GerritChange(change=2341)])) +
      api.properties(
          TestInputProperties(output_builds=[
              build_pb2.Build(id=123, builder=build_pb2.BuilderID(
                  builder='betty')),
              build_pb2.Build(id=231, builder=build_pb2.BuilderID(
                  builder='reef'))
          ])))

  struct_value = struct_pb2.Struct(
      fields={
          'reef': struct_pb2.Value(string_value='success'),
          'betty': struct_pb2.Value(string_value='failure'),
      })
  properties = struct_pb2.Struct(fields={
      'build_target_test_status': struct_pb2.Value(struct_value=struct_value)
  })
  yield (api.test('passed_targets_with_history') +
         api.buildbucket.simulated_search_results([
             build_pb2.Build(
                 id=123, output=build_pb2.Build.Output(properties=properties))
         ], 'Looking for successful tests (2).buildbucket.search') +
         api.properties(
             TestInputProperties(
                 input_target_patches=[common_pb2.GerritChange(change=2341)])) +
         api.properties(TestInputProperties(output_targets=['reef'])))
