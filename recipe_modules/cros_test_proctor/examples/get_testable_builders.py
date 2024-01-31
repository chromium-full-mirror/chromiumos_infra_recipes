# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_test_proctor',
]



def RunSteps(api):
  builds = [
      json_format.Parse(b, build_pb2.Build())
      for b in api.properties.get('builds', [])
  ]
  gerrit_changes = api.buildbucket.build.input.gerrit_changes
  testable_builders = api.cros_test_proctor.get_testable_builders(
      gerrit_changes, builds)
  api.assertions.assertCountEqual(
      testable_builders, api.properties.get('expected_testable_builders', []))


def GenTests(api):
  gerrit_changes = [
      GerritChange(
          host='chromium-review.googlesource.com',
          project='src/projectA',
          change=123,
          patchset=3,
      ),
      GerritChange(
          host='chromium-review.googlesource.com',
          project='src/projectB',
          change=456,
          patchset=7,
      ),
  ]

  build = build_pb2.Build()
  build.builder.builder = 'target-cq'
  build.input.properties['build_target'] = {'name': 'target'}
  build = json_format.MessageToJson(build)

  yield api.test(
      'basic',
      api.buildbucket.try_build(builder='cq-orchestrator',
                                gerrit_changes=gerrit_changes),
      api.properties(builds=[build], expected_testable_builders=['target-cq']),
      api.post_process(post_process.MustRun, 'find relevant plans'),
      api.post_process(post_process.MustRun, 'get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-plans',
      api.buildbucket.try_build(builder='cq-orchestrator',
                                gerrit_changes=gerrit_changes),
      api.properties(builds=[build]),
      api.step_data(
          'find relevant plans.src/projectA.list output files',
          api.file.listdir([]),
      ),
      api.step_data(
          'find relevant plans.src/projectB.list output files',
          api.file.listdir([]),
      ),
      api.post_process(post_process.DoesNotRun, 'get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-builds',
      api.buildbucket.try_build(builder='cq-orchestrator',
                                gerrit_changes=gerrit_changes),
      api.post_process(post_process.DoesNotRun, 'find relevant plans'),
      api.post_process(post_process.DoesNotRun, 'get testable builders'),
      api.post_process(post_process.DropExpectation),
  )

  no_target_build = build_pb2.Build()
  no_target_build.builder.builder = 'no-target-cq'
  no_target_build = json_format.MessageToJson(no_target_build)
  yield api.test(
      'no-builds-with-build-target',
      api.buildbucket.try_build(builder='cq-orchestrator',
                                gerrit_changes=gerrit_changes),
      api.properties(builds=[no_target_build]),
      api.post_process(post_process.DoesNotRun, 'find relevant plans'),
      api.post_process(post_process.DoesNotRun, 'get testable builders'),
      api.post_process(post_process.DropExpectation),
  )
