# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Callable
from typing import Dict

from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'checkpoint',
]



def RunSteps(api: RecipeApi):
  api.checkpoint.register()
  _ = api.checkpoint.original_build_bbid

  with api.checkpoint.retry(RetryStep.STAGE_ARTIFACTS) as run_step:
    if run_step:
      api.assertions.assertTrue(
          api.checkpoint.is_run_step(RetryStep.STAGE_ARTIFACTS))
      api.step('stage artifacts', ['echo', 'stage_artifacts'])
      api.assertions.assertFalse(
          api.checkpoint.is_run_step(RetryStep.RUN_FAILED_CHILDREN))

  with api.checkpoint.retry(RetryStep.PUSH_IMAGES) as run_step:
    if run_step:
      api.assertions.assertTrue(
          api.checkpoint.is_run_step(RetryStep.PUSH_IMAGES))
      api.step('push images', ['echo', 'push_images'])

  with api.checkpoint.retry(RetryStep.COLLECT_SIGNING) as run_step:
    if run_step:
      api.assertions.assertTrue(
          api.checkpoint.is_run_step(RetryStep.COLLECT_SIGNING))
      api.step('collect signing', ['echo', 'collect_signing'])


def GenTests(api: RecipeApi):

  def SummaryMarkdownEquals(check: Callable[[str, bool], bool],
                            step_odict: Dict[str, Step], message: str):
    """Assert that the summary markdown equals the string."""
    summary_markdown = step_odict['$result']['failure']['humanReason']
    check('summary markdown == expected', summary_markdown == message)

  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.input.properties['recipe'] = 'build_release'
  original_build.output.properties[
      'artifact_link'] = 'gs://chromeos-image-archive/staging-octopus-release-main/R110-15274.0.0-8922054662172514001'
  original_build.output.properties['signing_instructions_uris'] = ['foo', 'bar']
  original_build.output.properties[
      'build_report_uri'] = 'gs://foo/build_report.json'

  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.MustRun, 'stage artifacts'),
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SUCCESS',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SUCCESS',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS'
          }), api.post_process(post_process.DropExpectation))

  yield api.test(
      'create-buildspec',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.CREATE_BUILDSPEC]
                  },
              }
          }), api.post_check(post_process.DoesNotRun, 'RUNNING IN RETRY MODE'),
      api.post_check(post_process.MustRun, 'stage artifacts'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'collect-signing',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.COLLECT_SIGNING]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) not retrying STAGE_ARTIFACTS'),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) not retrying PUSH_IMAGES'),
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SKIPPED',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SKIPPED',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS'
          }), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-bbid',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }),
      api.post_check(post_process.StepFailure, 'RUNNING IN RETRY MODE'),
      api.post_check(SummaryMarkdownEquals, 'no bbid specified'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'bad-build',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          None, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.StepFailure, 'RUNNING IN RETRY MODE'),
      api.post_check(SummaryMarkdownEquals,
                     'could not fetch build 8922054662172514001'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test('full-run',
                 api.properties(**{'$chromeos/checkpoint': {
                     'retry': False,
                 }}), api.post_check(post_process.MustRun, 'stage artifacts'),
                 api.post_process(post_process.DropExpectation))

  yield api.test(
      'skip-stage-artifacts',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.PUSH_IMAGES]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) not retrying STAGE_ARTIFACTS'),
      api.post_check(post_process.DoesNotRun, 'stage artifacts'),
      api.post_check(
          post_process.PropertyEquals, 'retry_summary', {
              RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'SKIPPED',
              RetryStep.Name(RetryStep.PUSH_IMAGES): 'SUCCESS',
              RetryStep.Name(RetryStep.COLLECT_SIGNING): 'SUCCESS'
          }), api.post_process(post_process.DropExpectation))

  yield api.test(
      'step-failure',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }),
      api.step_data('stage artifacts', retcode=1),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.MustRun, 'stage artifacts'),
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): 'FAILED'}),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  no_artifacts_link = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  no_artifacts_link.input.properties['recipe'] = 'build_release'
  yield api.test(
      'skip-stage-artifacts-missing-artifact-link',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.PUSH_IMAGES]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          no_artifacts_link,
          step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.StepFailure,
                     'RUNNING IN RETRY MODE.verify previous build'),
      api.post_check(post_process.DoesNotRun, 'stage artifacts'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  no_signing_uris = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  no_signing_uris.input.properties['recipe'] = 'build_release'
  no_signing_uris.output.properties[
      'build_report_uri'] = 'gs://foo/build_report.json'
  no_signing_uris.output.properties[
      'artifact_link'] = 'gs://chromeos-image-archive/staging-octopus-release-main/R110-15274.0.0-8922054662172514001'
  yield api.test(
      'skip-stage-artifacts-missing-signing-uris',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.DEBUG_SYMBOLS]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          no_signing_uris,
          step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.StepFailure,
                     'RUNNING IN RETRY MODE.verify previous build'),
      api.post_check(post_process.DoesNotRun, 'stage artifacts'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  no_build_report_uri = build_pb2.Build(id=8922054662172514001,
                                        status='FAILURE')
  no_build_report_uri.input.properties['recipe'] = 'build_release'
  no_build_report_uri.output.properties[
      'artifact_link'] = 'gs://chromeos-image-archive/staging-octopus-release-main/R110-15274.0.0-8922054662172514001'
  yield api.test(
      'missing-build-report-uri',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '8922054662172514001',
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }),
      api.buildbucket.simulated_get(
          no_build_report_uri,
          step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.StepFailure,
                     'RUNNING IN RETRY MODE.verify previous build'),
      api.post_check(post_process.DoesNotRun, 'stage artifacts'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
