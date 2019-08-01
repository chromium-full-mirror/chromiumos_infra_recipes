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

from PB.recipe_modules.chromeos.cros_history.examples.get_passed_builds import GetPassedBuildsProperties

PROPERTIES = GetPassedBuildsProperties


def RunSteps(api, properties):
  if properties.input_build_patches:
    previous_builds = api.cros_history.get_passed_builds()
    api.assertions.assertItemsEqual(previous_builds, properties.output_builds)


def GenTests(api):
  yield (
      api.test('patch_without_history') +
      api.buildbucket.simulated_search_results(
          [], 'get change build history.buildbucket.search') + api.properties(
              GetPassedBuildsProperties(input_build_patches=[
                  common_pb2.GerritChange(change=1234),
              ])) +
      api.properties(
          GetPassedBuildsProperties(
              input_target_patches=[common_pb2.GerritChange(change=2341)])))

  yield (
      api.test('passed_builds_with_history') +
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, builder=build_pb2.BuilderID(builder='betty'),
                          status=common_pb2.SUCCESS),
          build_pb2.Build(id=231, builder=build_pb2.BuilderID(builder='reef'),
                          status=common_pb2.SUCCESS),
          build_pb2.Build(id=312, builder=build_pb2.BuilderID(
              builder='cq-orch'), status=common_pb2.SUCCESS),
      ], 'get change build history.buildbucket.search') + api.buildbucket.build(
          build_pb2.Build(builder=build_pb2.BuilderID(builder='cq-orch'))) +
      api.properties(
          GetPassedBuildsProperties(
              input_build_patches=[common_pb2.GerritChange(change=2341)])) +
      api.properties(
          GetPassedBuildsProperties(output_builds=[
              build_pb2.Build(id=123, builder=build_pb2.BuilderID(
                  builder='betty'), status=common_pb2.SUCCESS),
              build_pb2.Build(id=231, builder=build_pb2.BuilderID(
                  builder='reef'), status=common_pb2.SUCCESS)
          ])))
