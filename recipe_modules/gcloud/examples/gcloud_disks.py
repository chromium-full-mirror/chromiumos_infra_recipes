# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'gcloud',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  # Multiple disks
  with api.gcloud.cleanup_attached_disks(), \
       api.gcloud.cleanup_mounted_disks():
    api.gcloud.attach_disk(name='cache_test1', instance='test_bot1',
                           disk='test_disk1', zone='us-central1-b')
    api.gcloud.attach_disk(name='cache_test2', instance='test_bot1',
                           disk='test_disk2', zone='us-central1-b')
    api.gcloud.mount_disk(name='cache_test1', mount_path='/tmp/cache1')
    api.gcloud.mount_disk(name='cache_test2', mount_path='/tmp/cache2')

  # Empty context
  with api.gcloud.cleanup_attached_disks(), \
       api.gcloud.cleanup_mounted_disks():
    pass

  # Unmount warning
  api.gcloud._unmount_disk(name='cache_test3', mount_path='/tmp/cache3')
  # Detach warning
  api.gcloud.detach_disk(instance='test_bot1', disk='test_disk3',
                         zone='us-central1-b')


def GenTests(api):
  yield api.test('basic')
