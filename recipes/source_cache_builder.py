# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS source cache snapshots."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/depot_tools',
    'depot_tools/gsutil',
    'build_menu',
    'chrome',
    'cros_cache',
    'easy',
    'gcloud',
    'repo',
    'src_state',
]

import re
from recipe_engine.recipe_api import StepFailure

from PB.recipes.chromeos.source_cache_builder import (
    SourceCacheBuilderProperties)

PROPERTIES = SourceCacheBuilderProperties

_SWARMING_HOST_REGEXP = (r'^chromeos-ci-'
                         r'(?P<role>[a-zA-Z]*)-'
                         r'(?P<zone>[a-zA-Z0-9]*-[a-zA-Z0-9]*-[a-zA-Z0-9]*)-'
                         r'(?P<suffix>.*)')


def RunSteps(api, properties):
  with api.step.nest('source cache update'):
    with api.step.nest('get swarming hostname'):
      infra_host = api.swarming.bot_id
      m = re.search(_SWARMING_HOST_REGEXP, infra_host)
      if not m:
        raise StepFailure(
            'failed to get zone from swarming host: {}'.format(infra_host))
      is_staging = api.build_menu.is_staging
      snapshot_prefixes = []
    with api.step.nest('attach gcloud compute cache disks'):
      with api.gcloud.cleanup_gce_disks(), \
           api.gcloud.cleanup_mounted_disks():
        for cache in properties.cache_definition:
          snapshot_prefixes.append(cache.snapshot_prefix)
          gen_suffix = api.time.ms_since_epoch()
          disk = '{}-{}-{}'.format(cache.compute_disk, gen_suffix,
                                   m.group('zone'))
          if is_staging:
            disk = '{}-{}'.format('staging', disk)
          cat_res = api.gsutil.cat(
              'gs://{}/{}'.format(properties.cache_bucket, cache.version_file),
              infra_step=True, stdout=api.raw_io.output())
          ret = cat_res.stdout.strip()
          try:
            api.gcloud.create_disk(disk=disk, zone=m.group('zone'),
                                   snapshot=ret, disk_type='pd-ssd')
          except StepFailure:
            api.gcloud.create_disk(disk=disk, zone=m.group('zone'),
                                   snapshot=cache.recovery_snapshot,
                                   disk_type='pd-ssd')
          api.gcloud.attach_disk(name=cache.cache_name, instance=infra_host,
                                 disk=disk, zone=m.group('zone'))
          mount_path = api.gcloud.mount_disk(name=cache.cache_name,
                                             mount_path=cache.cache_directory,
                                             recipe_mount=True)
          with api.step.nest('sync mounted cache directories'):
            snapshot_name = '{}-{}'.format(cache.snapshot_prefix, gen_suffix)
            try:
              if cache.command == 'repo':
                with api.context(cwd=mount_path):
                  sync_opts = dict(force_sync=True, detach=True, jobs=20,
                                   retry_fetches=8, timeout=10800,
                                   force_remove_dirty=True)
                  init_opts = dict(
                      verbose=True, manifest_branch='{}snapshot'.format(
                          'staging-' if is_staging else ''))
                  api.repo.ensure_synced_checkout(
                      mount_path, api.src_state.internal_manifest.url,
                      init_opts=init_opts, sync_opts=sync_opts,
                      final_cleanup=True)
              if cache.command == 'gclient':
                # Chrome cache consists of a local repo cache and src,
                # both mounted via a single disk. We change into the
                # source directory to sync.
                api.chrome.cache_sync(cache_path=mount_path)
            # If sync fails, recovery to known working for next execution.
            except StepFailure:
              api.cros_cache.write_and_upload_version(properties.cache_bucket,
                                                      cache.version_file,
                                                      cache.recovery_snapshot)
              break
          with api.step.nest('sync disk cache before snapshot'):
            api.gcloud.sync_disk_cache(name=cache.cache_name)
          with api.step.nest('unmount disk for snapshot'):
            api.gcloud.unmount_disk(name=cache.cache_name,
                                    mount_path=mount_path)
          with api.step.nest('detach disk for snapshot'):
            api.gcloud.detach_disk(instance=infra_host, disk=disk,
                                   zone=m.group('zone'))
          with api.step.nest('snapshot synced disk'):
            api.gcloud.snapshot_disk(disk, snapshot_name, m.group('zone'))
          with api.step.nest('upload updated version file'):
            api.cros_cache.write_and_upload_version(properties.cache_bucket,
                                                    cache.version_file,
                                                    snapshot_name)
    with api.step.nest('cleanup expired snapshots'):
      snapshot_delete_list = api.gcloud.get_expired_snapshots(
          retention_days=properties.retention_days, prefixes=snapshot_prefixes,
          protected_snapshots=properties.protected_snapshots)
      api.easy.set_properties_step(expired_snapshots=snapshot_delete_list)
      api.gcloud.delete_snapshots(snapshots=snapshot_delete_list)


def GenTests(api):

  yield api.test('basic')

  yield api.test(
      'attach-chromeos-disk',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          cache_definition=[
              dict(
                  cache_name='test-cache',
                  cache_directory='test-cache',
                  compute_disk='test-disk1',
                  snapshot_prefix='test-cache-prefix',
                  version_file='test-cache-version',
                  command='repo',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ))

  yield api.test(
      'staging-execution',
      api.buildbucket.generic_build(builder="staging_SourceCacheBuilder",
                                    bucket='staging'),
      api.swarming.properties(
          bot_id='chromeos-ci-staging-us-central1-b-x16-0-nvcj'),
      api.properties(
          cache_definition=[
              dict(
                  cache_name='test-cache',
                  cache_directory='test-cache',
                  compute_disk='test-disk1',
                  snapshot_prefix='test-cache-prefix',
                  version_file='test-cache-version',
                  command='repo',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ))

  yield api.test(
      'sync-caches',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  cache_directory='chromeos',
                  compute_disk='test-disk1',
                  snapshot_prefix='test-chromeos-prefix',
                  version_file='test-chromeos-version',
                  command='repo',
              ),
              dict(
                  cache_name='chrome',
                  cache_directory='chrome',
                  compute_disk='test-disk2',
                  snapshot_prefix='test-chrome-prefix',
                  version_file='test-chrome-version',
                  command='gclient',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ))

  yield api.test(
      'sync-cache-step-failure',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  cache_directory='chromeos',
                  compute_disk='test-disk1',
                  snapshot_prefix='test-chromeos-prefix',
                  version_file='test-chromeos-version.txt',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ),
      api.step_data((
          'source cache update.attach gcloud compute cache disks.sync mounted cache directories.Write proto to [CLEANUP]/snapshot/chromeos/.recipes_state.json (2)'
      ), retcode=3),
  )

  yield api.test(
      'create-disk-step-failure',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  cache_directory='chromeos',
                  compute_disk='test-disk1',
                  snapshot_prefix='test-chromeos-prefix',
                  version_file='test-chromeos-version.txt',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ),
      api.step_data((
          'source cache update.attach gcloud compute cache disks.create disk from snapshot'
      ), retcode=3),
  )
