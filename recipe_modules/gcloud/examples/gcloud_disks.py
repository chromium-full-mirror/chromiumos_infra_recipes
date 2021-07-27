# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'gcloud',
]


def RunSteps(api):
  # Multiple disks
  with api.gcloud.cleanup_gce_disks(), \
       api.gcloud.cleanup_mounted_disks():
    api.gcloud.create_disk(disk='test_disk1', zone='us-central1-b',
                           snapshot='test-chromeos-snapshot',
                           disk_type='pd-ssd')
    api.gcloud.create_disk(disk='test_disk2', zone='us-central1-b',
                           snapshot='test-chrome-snapshot')
    api.gcloud.attach_disk(name='cache_test1', instance='test_bot1',
                           disk='test_disk1', zone='us-central1-b')
    api.gcloud.attach_disk(name='cache_test2', instance='test_bot1',
                           disk='test_disk2', zone='us-central1-b')
    api.gcloud.mount_disk(name='cache_test1', mount_path='cache1',
                          recipe_mount=True)
    api.gcloud.mount_disk(name='cache_test2', mount_path='cache2')
    api.gcloud.sync_disk_cache(name='cache_test1')
    api.gcloud.sync_disk_cache(name='cache_test2')
    api.gcloud.snapshot_disk(disk='test_disk1',
                             snapshot_name='test_disk1_snapshot',
                             zone='us-central1-b')
    api.gcloud.snapshot_disk(disk='test_disk2',
                             snapshot_name='test_disk2_snapshot',
                             zone='us-central1-b')
    prefixes = [
        'staging-chromeos-cache-snapshot', 'staging-chrome-cache-snapshot'
    ]
    protected_snapshots = ['staging-chrome-cache-snapshot-1625886728983']
    snapshot_list = api.gcloud.get_expired_snapshots(
        retention_days=7, prefixes=prefixes,
        protected_snapshots=protected_snapshots)
    api.assertions.assertEqual([
        'staging-chromeos-cache-snapshot-1625890262392',
        'staging-chromeos-cache-snapshot-1625893935790'
    ], snapshot_list)
    api.gcloud.delete_snapshots(snapshots=snapshot_list)

  # Empty context
  with api.gcloud.cleanup_gce_disks(), \
       api.gcloud.cleanup_mounted_disks():
    pass

  # Unmount warning
  api.gcloud.unmount_disk(name='cache_test3', mount_path='cache3')
  # Detach warning
  api.gcloud.detach_disk(instance='test_bot1', disk='test_disk3',
                         zone='us-central1-b')



def GenTests(api):
  yield api.test('basic')
