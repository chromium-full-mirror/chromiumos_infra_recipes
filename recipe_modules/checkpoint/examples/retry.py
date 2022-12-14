# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Callable, Dict

from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.checkpoint.checkpoint import RetryStep

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'checkpoint',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  api.checkpoint.register()

  with api.checkpoint.retry(RetryStep.STAGE_ARTIFACTS) as run_step:
    if run_step:
      api.assertions.assertTrue(
          api.checkpoint.will_run_step(RetryStep.STAGE_ARTIFACTS))
      api.step('stage artifacts', ['echo', 'foo'])


def GenTests(api: RecipeApi):

  def SummaryMarkdownEquals(check: Callable[[str, bool], bool],
                            step_odict: Dict[str, Step], message: str):
    """Assert that the summary markdown equals the string."""
    summary_markdown = step_odict['$result']['failure']['humanReason']
    check('summary markdown == expected', summary_markdown == message)

  original_build = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  original_build.output.properties[
      'artifact_link'] = 'gs://chromeos-image-archive/staging-octopus-release-main/R110-15274.0.0-8922054662172514001'

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
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): "SUCCESS"}),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

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
          }), api.post_check(post_process.StepFailure, 'RUNNING IN RETRY MODE'),
      api.post_check(SummaryMarkdownEquals, 'no bbid specified'),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation))

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
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation))

  yield api.test('full-run',
                 api.properties(**{'$chromeos/checkpoint': {
                     'retry': False,
                 }}), api.post_check(post_process.MustRun, 'stage artifacts'),
                 api.post_check(post_process.StatusSuccess),
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
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): "SKIPPED"}),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  no_artifacts_link = build_pb2.Build(id=8922054662172514001, status='FAILURE')
  yield api.test(
      'skip-stage-artifacts-missing-property',
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
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation))

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
          }), api.step_data('stage artifacts', retcode=1),
      api.buildbucket.simulated_get(
          original_build, step_name='RUNNING IN RETRY MODE.get original build'),
      api.post_check(post_process.MustRun, 'stage artifacts'),
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): "FAILED"}),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation))
