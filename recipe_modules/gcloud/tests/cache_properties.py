# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.gcloud.tests.tests import \
    CachePropertiesProperties

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


PROPERTIES = CachePropertiesProperties


def RunSteps(api, properties):
  api.gcloud.setup_cache_disk(cache_name='chromiumos', branch='main',
                              recipe_mount=True,
                              recovery_snapshot=properties.recovery_snapshot)
  if properties.mounted_snapshot:
    api.assertions.assertEqual(api.gcloud.mounted_snapshot,
                               properties.mounted_snapshot)
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
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'recovery-image',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
          }
      }),
      api.gcloud.set_image_exists_data([{
          'name': 'initial-chromiumos-source-snapshot'
      }]),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=initial-chromiumos-source-snapshot']),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'recovery-image-fallback',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
          }
      }),
      api.gcloud.set_image_exists_data([{
          'name': 'initial-chromiumos-source-snapshot-fallback'
      }]),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=initial-chromiumos-source-snapshot-fallback']),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'custom-recovery-image',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
          }
      }),
      api.properties(recovery_snapshot='super-custom-snapshot'),
      api.gcloud.set_image_exists_data([{
          'name': 'super-custom-snapshot'
      }]),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=super-custom-snapshot']),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'custom-recovery-image-fallback',
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
          }
      }),
      api.properties(recovery_snapshot='super-custom-snapshot'),
      api.gcloud.set_image_exists_data([{
          'name': 'super-custom-snapshot-fallback'
      }]),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=super-custom-snapshot-fallback']),
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
      api.properties(mounted_snapshot='test-cache-snapshot-123'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          ['--image=test-cache-snapshot-123']),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'chromeos-release-bot',
      api.properties(
          **{'$chromeos/gcloud': {
              'gce_project': 'chromeos-release-bot'
          }}),
      api.post_check(
          post_process.StepCommandContains,
          'source cache.setup source cache disk.create disk from snapshot image.check whether image exists: ',
          ['--project', 'chromeos-bot']),
      api.post_check(post_process.DropExpectation),
  )
