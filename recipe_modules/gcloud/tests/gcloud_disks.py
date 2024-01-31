# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

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
                           image='test-chromeos-snapshot', disk_type='pd-ssd',
                           size='200GB')
    api.gcloud.create_disk(disk='test_disk2', zone='us-central1-b',
                           image='test-chrome-snapshot')
    api.gcloud.attach_disk(name='cache_test1', instance='test_bot1',
                           disk='test_disk1', zone='us-central1-b')
    api.gcloud.attach_disk(name='cache_test2', instance='test_bot1',
                           disk='test_disk2', zone='us-central1-b')

    # This remove tests the feature where we can reattach a disk that some other
    # builder has left behind (by asking fstab for the ref if we don't have it).
    api.gcloud._attached_disks.pop('cache_test1')  # pylint: disable=protected-access

    api.gcloud.mount_disk(name='cache_test1', mount_path='cache1',
                          recipe_mount=True)
    api.gcloud.mount_disk(name='cache_test2', mount_path='cache2')
    api.gcloud.sync_disk_cache(name='cache_test1')
    api.gcloud.sync_disk_cache(name='cache_test2')
    api.gcloud.create_image_from_disk(disk='test_disk1',
                                      image_name='test_disk1_snapshot',
                                      zone='us-central1-b')
    api.gcloud.create_image_from_disk(disk='test_disk2',
                                      image_name='test_disk2_snapshot',
                                      zone='us-central1-b')
    prefixes = [
        'staging-chromeos-cache-snapshot', 'staging-chrome-cache-snapshot'
    ]
    protected_snapshots = ['staging-chrome-cache-snapshot-16258867']
    image_list = api.gcloud.get_expired_images(
        retention_days=7, prefixes=prefixes,
        protected_images=protected_snapshots)
    api.assertions.assertEqual([
        'staging-chromeos-cache-snapshot-16258939',
        'staging-chromeos-cache-snapshot-16258902',
    ], image_list)
    api.gcloud.delete_images(images=image_list)
    disk_list = api.gcloud.list_all_disks()
    instance_list = api.gcloud.list_all_instances()
    disks_to_delete = api.gcloud.determine_disks_to_delete(
        disks=disk_list, instances=instance_list)
    api.assertions.assertDictEqual(
        disks_to_delete, {
            'chromeos-ci-infra-us-central1-b-x16-0-lmno-cros':
                'us-central1-b',
            'chromeos-ci-infra-us-central1-b-x16-0-lmno-cros-internal':
                'us-central1-b'
        })

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
