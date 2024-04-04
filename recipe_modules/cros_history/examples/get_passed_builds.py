# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from PB.recipe_modules.chromeos.cros_history.examples.get_passed_builds import (
    GetPassedBuildsProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'cros_history',
]


PROPERTIES = GetPassedBuildsProperties


def RunSteps(api, properties):
  if properties.input_build_patches:
    previous_builds = api.cros_history.get_passed_builds()
    api.assertions.assertCountEqual(previous_builds, properties.output_builds)


def _build_with_changes(build):
  build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
  return build


def GenTests(api):
  yield api.test(
      'patch-without-history', api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.simulated_multi_predicates_search_results(
          [], 'get change build history.buildbucket.search'),
      api.properties(
          GetPassedBuildsProperties(input_build_patches=[
              common_pb2.GerritChange(change=1234),
          ])),
      api.properties(
          GetPassedBuildsProperties(
              input_target_patches=[common_pb2.GerritChange(change=2341)])))

  yield api.test(
      'passed-builds-with-history', api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.build(
          _build_with_changes(
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(builder='cq-orch'),
                  created_by='project:chromeos', tags=[{
                      'key': 'cq_equivalent_cl_group_key',
                      'value': 'GROUP_KEY'
                  }]))),
      api.buildbucket.simulated_multi_predicates_search_results([
          _build_with_changes(
              build_pb2.Build(
                  id=123, builder=builder_common_pb2.BuilderID(builder='betty'),
                  status=common_pb2.SUCCESS,
                  start_time=timestamp_pb2.Timestamp(seconds=122))),
          _build_with_changes(
              build_pb2.Build(
                  id=122, builder=builder_common_pb2.BuilderID(builder='betty'),
                  status=common_pb2.SUCCESS,
                  start_time=timestamp_pb2.Timestamp(seconds=124))),
          _build_with_changes(
              build_pb2.Build(
                  id=231, builder=builder_common_pb2.BuilderID(builder='reef'),
                  status=common_pb2.SUCCESS,
                  start_time=timestamp_pb2.Timestamp(seconds=122))),
          _build_with_changes(
              build_pb2.Build(
                  id=312, builder=builder_common_pb2.BuilderID(
                      builder='cq-orch'), status=common_pb2.SUCCESS,
                  start_time=timestamp_pb2.Timestamp(seconds=124))),
      ], 'get change build history.buildbucket.search'),
      api.properties(
          GetPassedBuildsProperties(
              input_build_patches=[common_pb2.GerritChange(change=2341)])),
      api.properties(
          GetPassedBuildsProperties(output_builds=[
              _build_with_changes(
                  build_pb2.Build(
                      id=122, builder=builder_common_pb2.BuilderID(
                          builder='betty'), status=common_pb2.SUCCESS,
                      start_time=timestamp_pb2.Timestamp(seconds=124))),
              _build_with_changes(
                  build_pb2.Build(
                      id=231, builder=builder_common_pb2.BuilderID(
                          builder='reef'), status=common_pb2.SUCCESS,
                      start_time=timestamp_pb2.Timestamp(seconds=122)))
          ])))
