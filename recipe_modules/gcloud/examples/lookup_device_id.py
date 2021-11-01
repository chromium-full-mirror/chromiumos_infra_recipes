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
  api.gcloud.create_disk_from_image(disk='chromiumos', zone='us-central1-b',
                                    image='test-chromeos-snapshot',
                                    disk_type='pd-ssd')
  api.gcloud.attach_disk(name='cros', instance='test_bot1', disk='test_disk1',
                         zone='us-central1-b')
  api.assertions.assertEqual(api.gcloud.disk_attached(disk_name='cros'), True)
  api.assertions.assertEqual(
      api.gcloud.lookup_device_id(disk_name='cros'), 'sdz')
  api.assertions.assertEqual(api.gcloud.gce_disk_blkid, 'sdz')
  api.gcloud.create_disk_from_image(disk='foo', zone='us-central1-b',
                                    image='test-chromeos-snapshot',
                                    disk_type='pd-ssd')
  api.gcloud.attach_disk(name='foo', instance='test_bot1', disk='test_disk1',
                         zone='us-central1-b')
  api.assertions.assertEqual(api.gcloud.disk_attached(disk_name='foo'), False)


def GenTests(api):
  yield api.test('basic')
