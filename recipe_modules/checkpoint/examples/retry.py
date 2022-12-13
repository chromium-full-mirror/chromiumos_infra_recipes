# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

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
  with api.checkpoint.retry(RetryStep.STAGE_ARTIFACTS) as run_step:
    if run_step:
      api.assertions.assertTrue(
          api.checkpoint.will_run_step(RetryStep.STAGE_ARTIFACTS))
      api.step('stage artifacts', ['echo', 'foo'])


def GenTests(api: RecipeApi):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }), api.post_check(post_process.MustRun, 'stage artifacts'),
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): "SUCCESS"}),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test('full-run',
                 api.properties(**{'$chromeos/checkpoint': {
                     'retry': False,
                 }}), api.post_check(post_process.MustRun, 'stage artifacts'),
                 api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))

  yield api.test(
      'skipped',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'exec_steps': {
                      'steps': [RetryStep.PUSH_IMAGES]
                  },
              }
          }),
      api.post_check(post_process.MustRun,
                     '(RETRY-MODE) not retrying STAGE_ARTIFACTS'),
      api.post_check(post_process.DoesNotRun, 'stage artifacts'),
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): "SKIPPED"}),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'step-failure',
      api.properties(
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'exec_steps': {
                      'steps': [RetryStep.STAGE_ARTIFACTS]
                  },
              }
          }), api.step_data('stage artifacts', retcode=1),
      api.post_check(post_process.MustRun, 'stage artifacts'),
      api.post_check(post_process.PropertyEquals, 'retry_summary',
                     {RetryStep.Name(RetryStep.STAGE_ARTIFACTS): "FAILED"}),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation))
