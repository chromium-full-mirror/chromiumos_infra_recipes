# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test init_report_from_previous_build."""

from google.protobuf import json_format

from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'build_reporting',
    'checkpoint',
]


BuildStatus = BuildReport.BuildStatus


def RunSteps(api: RecipeApi):
  api.checkpoint.register()

  api.build_reporting.init_report_from_previous_build()
  if api.checkpoint.is_retry():
    build_report = api.build_reporting.merged_build_report
    api.assertions.assertEqual(build_report,
                               BuildReport(
                                   buildbucket_id=0,
                                   count=10,
                               ))


def GenTests(api: RecipeApi):
  previous_build_report = BuildReport(
      buildbucket_id=8922054662172514002,
      count=10,
  )

  original_build = build_pb2.Build(id=8922054662172514002, status='FAILURE')
  original_build.input.properties['recipe'] = 'build_release'
  original_build.output.properties[
      'build_report_uri'] = 'gs://chromeos-image-archive/staging-octopus-release-main/R110-15274.0.0-8922054662172514001/build_report.json'
  original_build.output.properties['signing_instructions_uris'] = ['foo', 'bar']

  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514002',
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.step_data(
          'read build report from previous build.gsutil cat',
          stdout=api.raw_io.output_text(
              json_format.MessageToJson(previous_build_report)),
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-retry', api.properties(**{'$chromeos/checkpoint': {
          'retry': False,
      }}),
      api.post_process(post_process.DoesNotRun,
                       'read build report from previous build.gsutil cat'),
      api.post_process(post_process.DropExpectation))
