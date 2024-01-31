# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2, common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'checkpoint',
]



def RunSteps(api: RecipeApi):
  api.checkpoint.register()
  api.assertions.assertEqual(api.checkpoint.builder_children(),
                             [8922054662172514002, 8922054662172514003])

  api.assertions.assertEqual(
      api.checkpoint.failed_builder_children()[0].builder.builder,
      'eve-release-main')

  api.assertions.assertEqual(api.checkpoint.successful_builder_children_bbids(),
                             [8922054662172514002])


def GenTests(api):
  original_build = build_pb2.Build(id=8922054662172514000, status='FAILURE')
  original_build.input.properties['recipe'] = 'orchestrator'
  original_build.output.properties['buildspec_gs_uri'] = 'gs://foo/1.xml'
  original_build.output.properties[
      'build_report_uri'] = 'gs://foo/build_report.json'
  original_build.output.properties['child_builds'] = [
      '8922054662172514001', '8922054662172514002', '8922054662172514003'
  ]

  def child_builds():
    builds = []
    builders = ['paygen-orchestrator', 'brya-release-main', 'eve-release-main']
    status = [common_pb2.FAILURE, common_pb2.SUCCESS, common_pb2.FAILURE]
    for i in range(3):
      build = build_pb2.Build(id=8922054662172514001 + i,
                              builder={'builder': builders[i]},
                              status=status[i])
      build.input.properties[
          'recipe'] = 'build_release' if i != 0 else 'paygen_orchestrator'
      builds.append(build)
    return builds

  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514000',
                  'exec_steps': {
                      'steps': [RetryStep.LAUNCH_TESTS]
                  }
              }
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.buildbucket.simulated_get_multi(
          child_builds(),
          step_name='RUNNING IN RETRY MODE.verify previous build.get child builder data'
      ),
      api.post_process(post_process.DropExpectation),
  )
