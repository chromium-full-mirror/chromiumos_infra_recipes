# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
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


def RunSteps(api):
  # Multiple disks
  mount_path = api.gcloud.setup_cache_disk(cache_name='chromiumos')
  api.assertions.assertEqual(api.gcloud.snapshot_suffix, '13370000')
  api.assertions.assertEqual(api.gcloud.host_zone, 'us-central1-b')
  if api.build_menu.is_staging:
    api.assertions.assertTrue(
        api.gcloud.check_for_disk_mount(mount_path='/tmp/', mock_mount=True))
    api.assertions.assertRegexpMatches(
        api.gcloud.gce_disk, r'chromeos-\w*-\w*-us-central1-b-x16-0-\w*-cros')
    api.assertions.assertEqual(
        api.gcloud.snapshot_version_file,
        'staging-chromiumos-main-cache-snapshot-version.txt')
  else:
    api.assertions.assertEqual(api.gcloud.snapshot_version_file,
                               'chromiumos-main-cache-snapshot-version.txt')
  api.gcloud.unmount_disk(name='chromiumos', mount_path=mount_path)
  api.gcloud.setup_cache_disk(cache_name='chromiumos',
                              branch='release-R90-13816.B', recipe_mount=True)
  api.assertions.assertEqual(api.gcloud.branch, 'release-r90-13816-b')
  api.assertions.assertEqual(api.gcloud.snapshot_suffix, '13370000')
  api.assertions.assertRegexpMatches(
      api.gcloud.gce_disk, r'chromeos-\w*-\w*-us-central1-b-x16-0-.*-crosr90')
  api.gcloud.setup_cache_disk(cache_name='chromiumos',
                              branch='stabilize-rust-13836.B')
  api.assertions.assertEqual(api.gcloud.branch, 'stabilize-rust-13836-b')
  api.assertions.assertRegexpMatches(
      api.gcloud.gce_disk,
      r'chromeos-\w*-\w*-us-central1-b-x16-0-.*-crosstabilize')
  api.gcloud.delete_disk(disk=api.gcloud.gce_disk, zone='us-central1-b')
  api.assertions.assertEqual(api.gcloud.snapshot_suffix, '13370000')


def GenTests(api):

  def mock_path(version_file):
    return api.path.exists(
        api.path['cache'].join('infra_versions').join(version_file))

  def mock_directory(cache_name):
    return api.path.exists(api.path['cache'].join(cache_name).join('upperdir'))

  yield api.test(
      'basic',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
  )
  yield api.test(
      'failed-to-get-zone-from-host',
      api.gcloud.infra_host('chromeos-ci-infra-x16-0-nvcj'),
  )
  yield api.test(
      'create-disk-step-failure',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.step_data((
          'setup source cache disk.create disk from snapshot image.check whether'
          + ' disk exists: chromeos-ci-infra-us-central1-b-x16-0-lmno-cros'),
                    retcode=404),
      api.step_data(
          'setup source cache disk.create disk from snapshot image.create disk from image',
          retcode=3),
  )
  yield api.test(
      'staging-execution',
      api.buildbucket.generic_build(builder="staging_SourceCacheBuilder",
                                    bucket='staging'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
  )
  yield api.test(
      'release-staging-execution',
      api.buildbucket.generic_build(builder="staging_SourceCacheBuilder",
                                    bucket='staging'),
      api.gcloud.infra_host(
          'chromeos-release-staging-us-central1-b-x16-0-nvcj'),
  )
  yield api.test(
      'local-version-file-exists',
      mock_path("chromiumos-main-cache-snapshot-version.txt"),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
  )
  yield api.test(
      'missing-version-file-in-storage',
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.step_data((
          'setup source cache disk.retrieve image version from storage.gsutil cat'
      ), retcode=3),
  )
  yield api.test(
      'upperdir-with-no-local-version',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
  )
  yield api.test(
      'local-version-snapshot-exists',
      mock_directory('chromiumos'),
      mock_path('chromiumos-main-cache-snapshot-version.txt'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.step_data('setup source cache disk.read local image version',
                    stdout=api.raw_io.output_text('chromiumos-main-16287984')),
  )
  yield api.test(
      'fail-to-create-disk-from-local-version',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-ssdf'),
      api.step_data((
          'setup source cache disk (2).create disk from snapshot image.create disk from image'
      ), retcode=3),
  )
  yield api.test(
      'overlayfs branch not set',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-ssdf'),
      api.step_data((
          'determine whether to reset overlayfs directories.read overlayfs branch'
      ), retcode=3),
  )
  yield api.test(
      'nothing returned on disk exists',
      mock_directory('chromiumos'),
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-ssdf'),
      api.step_data((
          'setup source cache disk (3).create disk from snapshot image.check whether'
          +
          ' disk exists: chromeos-ci-infra-us-central1-b-x16-0-ssdf-crosstabilize'
      ), retcode=404),
      api.post_check(post_process.StatusSuccess),
  )
