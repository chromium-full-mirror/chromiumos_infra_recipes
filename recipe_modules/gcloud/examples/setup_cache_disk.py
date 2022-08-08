# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.recipe_modules.chromeos.gcloud.examples.setup_cache_disk import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  if properties.should_fail:
    with api.assertions.assertRaises(StepFailure):
      api.gcloud.setup_cache_disk(cache_name='chromiumos', disk_size='600GB',
                                  disallow_previously_mounted=True)
  regexp_prefix = r'chromiumos' if properties.chromiumos_bot_prefix else r'chromeos'

  # Multiple disks
  mount_path = api.gcloud.setup_cache_disk(cache_name='chromiumos',
                                           disk_size='600GB')
  api.assertions.assertEqual(api.gcloud.snapshot_suffix, '13370000')
  api.assertions.assertEqual(api.gcloud.host_zone, 'us-central1-b')
  api.assertions.assertEqual(api.gcloud.disk_short_name, 'cros')
  if api.build_menu.is_staging:
    api.assertions.assertRegexpMatches(
        api.gcloud.gce_disk,
        regexp_prefix + r'-\w*-\w*-us-central1-b-x16-0-\w*-cros')
    api.assertions.assertEqual(
        api.gcloud.snapshot_version_file,
        'staging-chromiumos-main-cache-snapshot-version.txt')
  else:
    api.assertions.assertEqual(api.gcloud.snapshot_version_file,
                               'chromiumos-main-cache-snapshot-version.txt')
  api.gcloud.unmount_disk(name=api.gcloud.disk_short_name,
                          mount_path=mount_path)
  mount_path = api.gcloud.setup_cache_disk(cache_name='chromiumos',
                                           branch='release-R90-13816.B',
                                           recipe_mount=True)
  api.assertions.assertEqual(api.gcloud.branch, 'release-r90-13816-b')
  api.assertions.assertEqual(api.gcloud.snapshot_suffix, '13370000')
  api.assertions.assertRegexpMatches(
      api.gcloud.gce_disk,
      regexp_prefix + r'-\w*-\w*-us-central1-b-x16-0-.*-crosr90')
  api.gcloud.unmount_disk(name='cros-r90', mount_path=mount_path)
  api.gcloud.setup_cache_disk(cache_name='chromiumos',
                              branch='release-R90-13816.B', recipe_mount=True)
  api.gcloud.setup_cache_disk(cache_name='chromiumos',
                              branch='stabilize-rust-13836.B')
  api.assertions.assertEqual(api.gcloud.branch, 'stabilize-rust-13836-b')
  api.assertions.assertRegexpMatches(
      api.gcloud.gce_disk,
      regexp_prefix + r'-\w*-\w*-us-central1-b-x16-0-.*-crosstabilize')
  api.gcloud.delete_disk(disk=api.gcloud.gce_disk, zone='us-central1-b')
  api.assertions.assertEqual(api.gcloud.snapshot_suffix, '13370000')
  mount_path = api.gcloud.setup_cache_disk(cache_name='chromiumos',
                                           branch='master', recipe_mount=True)
  api.assertions.assertEqual(api.gcloud.branch, 'main')


def GenTests(api):

  def mock_directory(cache_name):
    return api.path.exists(api.path['cache'].join(cache_name).join('upperdir'))

  yield api.test(
      'basic',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'chromiumos-bot',
      api.properties(chromiumos_bot_prefix=True),
      api.gcloud.infra_host('chromiumos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'dont-reuse',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.gcloud.is_mount(True),
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
          }
      }),
      api.post_check(post_process.StatusSuccess),
      api.post_check(
          post_process.MustRun,
          'source cache.setup source cache disk.create disk from snapshot image.discarding mounted cache'
      ),
  )

  yield api.test(
      'is-mount',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.gcloud.is_mount(True),
      api.properties(should_fail=True),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'bad-config-no-specific-image',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(should_fail=True),
      api.properties(**{
          '$chromeos/gcloud': {
              'source_cache_action': 'MOUNT_SPECIFIC_IMAGE',
          }
      }),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'bad-config-image-but-wrong-action',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(should_fail=True),
      api.properties(
          **{
              '$chromeos/gcloud': {
                  'source_cache_action': 'MOUNT_RECOVERY_IMAGE',
                  'specific_image_to_mount': 'image-1234',
              }
          }),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'failed-to-get-zone-from-host',
      api.gcloud.infra_host('chromeos-ci-infra-x16-0-nvcj'),
      api.post_check(post_process.StatusFailure),
  )
  yield api.test(
      'create-disk-step-failure',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.step_data((
          'source cache.setup source cache disk.create disk from snapshot image.check whether'
          + ' disk exists: chromeos-ci-infra-us-central1-b-x16-0-lmno-cros'),
                    retcode=404),
      api.step_data(
          'source cache.setup source cache disk.create disk from snapshot image.create disk from image',
          retcode=3),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'resize-disk-but-same-size',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.step_data((
          'source cache.setup source cache disk.create disk from snapshot image.check whether'
          + ' disk exists: chromeos-ci-infra-us-central1-b-x16-0-lmno-cros'),
                    retcode=404),
      api.step_data('source cache.resize GCE disk', retcode=1),
      api.step_data(
          'source cache.resize GCE disk (2)', stdout=api.raw_io.output(
              'Some non-sequitur message to the disk size.\n'
              'New disk size \'10\' GiB must be larger '
              'than existing size \'10\' GiB.\n'), retcode=1),
      api.post_check(post_process.StatusSuccess),
  )
  yield api.test(
      'create-disk-fails-as-exists-but-404-before',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.step_data(
          'source cache (5).setup source cache disk.create disk from snapshot image.create disk from image',
          stdout=api.raw_io.output(
              'Some non-sequitur message to disk existing.\n'
              'The resource \'a/big/resource/thing\' already exists'),
          retcode=404),
      api.post_check(
          post_process.DoesNotRun,
          'source cache (5).setup source cache disk.create disk from snapshot image.create disk from image (2)'
      ),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'staging-execution',
      api.buildbucket.generic_build(builder="staging_SourceCacheBuilder",
                                    bucket='staging'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StatusSuccess),
  )
  yield api.test(
      'release-staging-execution',
      api.buildbucket.generic_build(builder="staging_SourceCacheBuilder",
                                    bucket='staging'),
      api.gcloud.infra_host(
          'chromeos-release-staging-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StatusSuccess),
  )
  yield api.test(
      'missing-version-file-in-storage',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.step_data((
          'source cache.setup source cache disk.retrieve image version from storage.gsutil cat'
      ), retcode=3),
      api.post_check(post_process.StatusSuccess),
  )
  yield api.test(
      'upperdir-with-no-local-version',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.post_check(post_process.StatusSuccess),
  )
  yield api.test(
      'overlayfs-branch-not-set',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-ssdf'),
      api.step_data((
          'source cache.determine whether to reset overlayfs directories.read overlayfs branch'
      ), retcode=3),
      api.post_check(post_process.StatusSuccess),
  )
  yield api.test(
      'nothing-returned-on-disk-exists',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-ssdf'),
      api.step_data((
          'source cache (4).setup source cache disk.create disk from snapshot image.check whether'
          +
          ' disk exists: chromeos-ci-infra-us-central1-b-x16-0-ssdf-crosstabilize'
      ), retcode=404),
      api.post_check(post_process.StatusSuccess),
  )
