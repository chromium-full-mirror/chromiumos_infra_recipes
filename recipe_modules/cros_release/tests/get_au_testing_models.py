# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_release.tests.get_au_testing_models import \
  GetAuTestingModelsProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_release',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GetAuTestingModelsProperties
BUILDER = 'octopus-release-main'


def RunSteps(api, properties):
  api.buildbucket.build.builder.builder = BUILDER
  actual_models = api.cros_release.get_au_testing_models(properties.fsi)
  api.assertions.assertCountEqual(actual_models, properties.expected_models)


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
  )

  yield api.test(
      'fsi',
      api.step_data(
          _fsi_generate_test_config_step, stdout=api.raw_io.output(
              '{"%s": {"model1": ["au"], "model2": []}}' % BUILDER)),
      api.properties(fsi=True),
      api.properties(expected_models=['model1', 'model2']),
  )

  yield api.test(
      'no-generate_test_config-response',
      api.step_data(_generate_test_config_step, stdout=api.raw_io.output('')),
      api.post_check(post_process.StepFailure, 'determine au testing models'),
      status='FAILURE',
  )

  yield api.test(
      'generate_test_config-response-does-not-contain-builder',
      api.step_data(
          _generate_test_config_step,
          stdout=api.raw_io.output('{"other_builder": {"foo": ["au"]}}')),
      api.post_check(post_process.StepFailure, 'determine au testing models'),
      status='FAILURE',
  )
