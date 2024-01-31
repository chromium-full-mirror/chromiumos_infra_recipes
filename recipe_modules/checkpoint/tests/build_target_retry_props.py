# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'checkpoint',
]



def RunSteps(api: RecipeApi):
  api.checkpoint.register()
  api.assertions.assertTrue(api.checkpoint.is_retry())

  api.assertions.assertEqual(
      api.checkpoint.builder_retry_props('octopus-release-main'), None)

  api.assertions.assertEqual(
      api.checkpoint.builder_retry_props('dedede-release-main'), {
          'retry': True,
          'original_build_bbid': '8922054662172514002',
          'exec_steps': {
              'steps': [
                  RetryStep.DEBUG_SYMBOLS, RetryStep.COLLECT_SIGNING,
                  RetryStep.PAYGEN
              ]
          },
      })
  api.assertions.assertEqual(
      api.checkpoint.builder_retry_props('eve-release-main'), {
          'retry': True,
          'original_build_bbid': '8922054662172514003',
          'exec_steps': {
              'steps': [
                  RetryStep.RUN_CHILDREN, RetryStep.RUN_FAILED_CHILDREN,
                  RetryStep.LAUNCH_TESTS, RetryStep.PAYGEN
              ]
          },
      })


def GenTests(api):
  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.input.properties['recipe'] = 'orchestrator'
  original_build.output.properties[
      'buildspec_gs_uri'] = 'gs://chromeos-manifest-versions/foo/1.xml'
  original_build.output.properties[
      'build_report_uri'] = 'gs://foo/build_report.json'
  original_build.output.properties['child_builds'] = [
      '8922054662172514002',
      '8922054662172514003',
  ]

  child_builds = []
  child_build = build_pb2.Build(id=8922054662172514002, status='FAILURE',
                                builder={'builder': 'dedede-release-main'})
  child_build.input.properties['recipe'] = 'build_release'
  child_build.input.properties['build_target'] = 'dedede'
  child_builds.append(child_build)
  child_build = build_pb2.Build(id=8922054662172514003, status='SUCCESS',
                                builder={'builder': 'eve-release-main'})
  child_build.input.properties['recipe'] = 'build_release'
  child_build.input.properties['build_target'] = 'eve'
  child_builds.append(child_build)

  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps':
                          [RetryStep.RUN_FAILED_CHILDREN, RetryStep.PAYGEN],
                  },
                  'builder_exec_steps': {
                      'dedede-release-main': {
                          'steps': [RetryStep.DEBUG_SYMBOLS],
                      },
                  },
              }
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.buildbucket.simulated_get_multi(
          child_builds,
          step_name='RUNNING IN RETRY MODE.verify previous build.get child builder data'
      ),
      api.post_process(post_process.DropExpectation),
  )
