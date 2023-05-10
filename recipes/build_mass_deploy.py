# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for modifying images for mass deployment. Intended for use with ChromeOS Flex."""

from PB.recipes.chromeos.build_mass_deploy import BuildMassDeployProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildMassDeployProperties

RELEASE_BUCKET = 'chromeos-releases'
THROWAWAY_BUCKET = 'chromeos-throw-away-bucket'


def RunSteps(api, properties):
  if not properties.input_image:
    raise StepFailure('`input_image` is required')

  working_dir = api.path.mkdtemp()
  with api.context(cwd=working_dir):
    with api.step.nest('download signed image'):
      api.gsutil.download(RELEASE_BUCKET, properties.input_image, 'image.zip')

    # Do work.
    with api.step.nest('do work'):
      output_filename = 'mass_deploy.zip'
      api.step('create deploy image', cmd=['touch', output_filename])

    # Construct path for new artifact, upload to GS.
    gs_dir = api.path.dirname(properties.input_image)
    gs_path = api.path.join(gs_dir, 'mass_deploy.zip')

    dest_bucket = RELEASE_BUCKET if properties.production else THROWAWAY_BUCKET
    api.gsutil.upload(output_filename, dest_bucket, gs_path)


def GenTests(api):
  yield api.test(
      'production',
      api.properties(**{
          'input_image': 'foo/bar.zip',
          'production': True,
      }),
      api.post_check(post_process.StepCommandContains,
                     'download signed image.gsutil download',
                     ['gs://chromeos-releases/foo/bar.zip']),
      api.post_check(post_process.MustRun, 'do work'),
      api.post_check(post_process.StepCommandContains, 'gsutil upload',
                     ['gs://chromeos-releases/foo/mass_deploy.zip']),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'non-production', api.properties(**{
          'input_image': 'foo/bar.zip',
      }),
      api.post_check(post_process.StepCommandContains,
                     'download signed image.gsutil download',
                     ['gs://chromeos-releases/foo/bar.zip']),
      api.post_check(post_process.MustRun, 'do work'),
      api.post_check(post_process.StepCommandContains, 'gsutil upload',
                     ['gs://chromeos-throw-away-bucket/foo/mass_deploy.zip']),
      api.post_process(post_process.DropExpectation))

  yield api.test('no-input-image',
                 api.post_process(post_process.DropExpectation),
                 status='FAILURE')
