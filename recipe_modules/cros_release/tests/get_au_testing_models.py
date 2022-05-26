# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_release',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine.recipe_api import Property
from recipe_engine import post_process

PROPERTIES = {
    'fsi':
        Property(
            kind=bool,
            help='Whether to get FSI-payload testing models.',
            default=False,
        ),
    'expected_models':
        Property(
            kind=list,
            help='List of models that should be returned by get_au_testing_models (not necessarily in the same order).',
            default=None)
}
BUILDER = 'octopus-release-main'


def RunSteps(api, fsi, expected_models):
  api.buildbucket.build.builder.builder = BUILDER
  actual_models = api.cros_release.get_au_testing_models(fsi)
  api.assertions.assertCountEqual(actual_models, expected_models)


def GenTests(api):
  _generate_test_config_step = '.'.join([
      'determine au testing models', 'generate target test requirements',
      'generate_test_config'
  ])
  _fsi_generate_test_config_step = '.'.join([
      'determine fsi testing models', 'generate target test requirements',
      'generate_test_config'
  ])

  yield api.test(
      'basic',
      api.step_data(
          _generate_test_config_step, stdout=api.raw_io.output(
              '{"%s": {"model1": ["au"], "model2": []}}' % BUILDER)),
      api.properties(expected_models=['model1']),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'fsi',
      api.step_data(
          _fsi_generate_test_config_step, stdout=api.raw_io.output(
              '{"%s": {"model1": ["au"], "model2": []}}' % BUILDER)),
      api.properties(fsi=True),
      api.properties(expected_models=['model1', 'model2']),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'no-generate_test_config-response',
      api.step_data(_generate_test_config_step, stdout=api.raw_io.output('')),
      api.post_check(post_process.StepFailure, 'determine au testing models'))

  yield api.test(
      'generate_test_config-response-does-not-contain-builder',
      api.step_data(
          _generate_test_config_step,
          stdout=api.raw_io.output('{"other_builder": {"foo": ["au"]}}')),
      api.post_check(post_process.StepFailure, 'determine au testing models'))
