# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'build_menu',
    'gcloud',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.gcloud.setup_cache_disk(cache_name='chromiumos', branch='master',
                              recipe_mount=True)
  api.assertions.assertEqual(api.gcloud.branch, 'main')


def GenTests(api):

  yield api.test(
      'fresh-sync',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'DONT_MOUNT_ANY_CACHE',
          }
      }),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      # Check some fresh sync properties.
      api.post_check(
          post_process.StepCommandDoesNotContain,
          'source cache.setup source cache disk.create disk with empty checkout.create empty disk',
          ['--image']),
      api.post_check(post_process.StepSuccess, 'source cache.chown the disk'),
      api.post_check(post_process.StepSuccess, 'source cache.repo init'),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'fresh-sync-ssd-fails',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'DONT_MOUNT_ANY_CACHE',
          }
      }),
      api.step_data(
          'source cache.setup source cache disk.create disk with empty checkout.create empty disk',
          retcode=3),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StepSuccess, 'source cache.chown the disk'),
      api.post_check(post_process.StepSuccess, 'source cache.repo init'),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'recovery-image',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
          }
      }),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=initial-chromiumos-source-snapshot']),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'specific-image',
      api.properties(
          **{
              '$chromeos/gcloud': {
                  'source_cache_action': 'MOUNT_SPECIFIC_IMAGE',
                  'specific_image_to_mount': 'test-cache-snapshot-123'
              }
          }),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=test-cache-snapshot-123']),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DropExpectation),
  )
