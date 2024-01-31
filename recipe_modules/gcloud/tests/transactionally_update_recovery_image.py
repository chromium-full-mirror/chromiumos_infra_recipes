# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from PB.recipe_modules.chromeos.gcloud.tests.tests import \
  TransactionallyUpdateRecoveryImageProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'gcloud',
]


PROPERTIES = TransactionallyUpdateRecoveryImageProperties


def RunSteps(api: RecipeApi,
             properties: TransactionallyUpdateRecoveryImageProperties):
  api.assertions.assertEqual(
      properties.expected_return or None,
      api.gcloud.transactionally_update_recovery_image(
          'image-123', 'chromeos', properties.recovery_image))


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  yield api.test(
      'image-does-not-exist',
      api.post_check(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'happy-path',
      api.properties(
          expected_return='initial-chromeos-source-snapshot-fallback'),
      api.gcloud.set_image_exists_data([{
          'name': 'image-123'
      }, {
          'name': 'initial-chromeos-source-snapshot'
      }]),
      api.post_check(post_process.MustRun, 'create image from image'),
      api.post_check(post_process.StepCommandContains,
                     'create image from image', [
                         'initial-chromeos-source-snapshot-fallback',
                         '--source-image=image-123'
                     ]),
      api.post_check(post_process.MustRun, 'delete image'),
      api.post_check(post_process.StepCommandContains, 'delete image',
                     ['initial-chromeos-source-snapshot']),
      api.post_check(post_process.MustRun, 'create image from image (2)'),
      api.post_check(
          post_process.StepCommandContains, 'create image from image (2)', [
              'initial-chromeos-source-snapshot',
              '--source-image=initial-chromeos-source-snapshot-fallback'
          ]),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'recovery-image-does-not-exist',
      api.gcloud.set_image_exists_data([{
          'name': 'image-123'
      }]),
      api.post_check(post_process.MustRun, 'create image from image'),
      api.post_check(
          post_process.StepCommandContains, 'create image from image',
          ['initial-chromeos-source-snapshot', '--source-image=image-123']),
      api.post_check(post_process.DoesNotRun, 'delete image'),
      api.post_check(post_process.DoesNotRun, 'create image from image (2)'),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'cleans-up-existing-fallback',
      api.properties(
          expected_return='initial-chromeos-source-snapshot-fallback'),
      api.gcloud.set_image_exists_data([{
          'name': 'image-123'
      }, {
          'name': 'initial-chromeos-source-snapshot'
      }, {
          'name': 'initial-chromeos-source-snapshot-fallback'
      }]),
      api.post_check(post_process.MustRun, 'delete image'),
      api.post_check(post_process.StepCommandContains, 'delete image',
                     ['initial-chromeos-source-snapshot-fallback']),
      api.post_check(post_process.MustRun, 'create image from image'),
      api.post_check(post_process.StepCommandContains,
                     'create image from image', [
                         'initial-chromeos-source-snapshot-fallback',
                         '--source-image=image-123'
                     ]),
      api.post_check(post_process.MustRun, 'delete image (2)'),
      api.post_check(post_process.StepCommandContains, 'delete image (2)',
                     ['initial-chromeos-source-snapshot']),
      api.post_check(post_process.MustRun, 'create image from image (2)'),
      api.post_check(
          post_process.StepCommandContains, 'create image from image (2)', [
              'initial-chromeos-source-snapshot',
              '--source-image=initial-chromeos-source-snapshot-fallback'
          ]),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'custom-recovery-image',
      api.properties(recovery_image='foooooo',
                     expected_return='foooooo-fallback'),
      api.gcloud.set_image_exists_data([{
          'name': 'image-123'
      }, {
          'name': 'foooooo'
      }]),
      api.post_check(post_process.MustRun, 'create image from image'),
      api.post_check(post_process.StepCommandContains,
                     'create image from image',
                     ['foooooo-fallback', '--source-image=image-123']),
      api.post_check(post_process.MustRun, 'delete image'),
      api.post_check(post_process.StepCommandContains, 'delete image',
                     ['foooooo']),
      api.post_check(post_process.MustRun, 'create image from image (2)'),
      api.post_check(post_process.StepCommandContains,
                     'create image from image (2)',
                     ['foooooo', '--source-image=foooooo-fallback']),
      api.post_check(post_process.DropExpectation),
  )
