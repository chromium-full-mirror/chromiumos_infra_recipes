# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS source cache snapshots."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'chrome',
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
    with api.step.nest('attach gcloud compute cache disks'):
      with api.gcloud.cleanup_gce_disks(), \
           api.gcloud.cleanup_mounted_disks():
        for cache in properties.cache_definition:
          disk = '{}-{}'.format(cache.compute_disk, m.group('zone'))
          if m.group('role') in ['staging']:
            disk = '{}-{}'.format('staging', disk)
          cat_res = api.gsutil.cat(
              'gs://{}/{}'.format(properties.cache_bucket, cache.version_file),
              infra_step=True, stdout=api.raw_io.output())
          ret = cat_res.stdout.strip()
          api.gcloud.create_disk(instance=infra_host, disk=disk,
                                 zone=m.group('zone'), snapshot=ret)
          api.gcloud.attach_disk(name=cache.cache_name, instance=infra_host,
                                 disk=disk, zone=m.group('zone'))
          mount_path = api.gcloud.mount_disk(name=cache.cache_name,
                                             mount_path=cache.cache_directory,
                                             recipe_mount=True)
          with api.step.nest('sync mounted cache directories'):
            if cache.command == 'repo':
              with api.context(cwd=mount_path):
                api.repo.sync(force_sync=True, detach=True, jobs=20,
                              no_tags=True, optimized_fetch=True,
                              retry_fetches=8, timeout=10800)
            if cache.command == 'gclient':
              # Chrome cache consists of a local repo cache and src, both mounted
              # via a single disk. We change into the source directory to sync.
              api.chrome.cache_sync(cache_path=mount_path)
          with api.step.nest('snapshot attached disk'):
            snapshot_name = '{}-{}'.format(cache.snapshot_prefix,
                                           api.time.ms_since_epoch())
            version_file_path = api.path['cleanup'].join(cache.version_file)
            api.gcloud.snapshot_disk(disk, snapshot_name, m.group('zone'))
            api.file.write_raw('write version file', version_file_path,
                               snapshot_name)
          with api.step.nest('upload updated version file'):
            api.gsutil.upload(version_file_path, properties.cache_bucket,
                              cache.version_file,
                              name='upload {}'.format(cache.version_file))
            api.easy.set_properties_step(
                **
                {'{}_snapshot_version'.format(cache.cache_name): snapshot_name})


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
      ))

  yield api.test(
      'staging-execution',
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
      ))
