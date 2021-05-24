# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'gcloud',
]

GCE_PROJECT = 'chromeos-gce-tests'


def RunSteps(api):
  api.gcloud.set_gce_project(project=GCE_PROJECT)
  api.gcloud.auth_list()
  api.gcloud.prep_image('chromeos-image-archive', 'image_path', 1234)
  api.gcloud.create_image('tar/path/1234.tar.gz', 'betty', 1234)
  api.gcloud.delete_image('image-name')
  api.gcloud.create_instance('image-name', project=GCE_PROJECT,
                             machine='n1-standard-4', zone='us-central1-a',
                             network='chromeos-gce-tests', subnet='us-central1')
  api.gcloud.delete_instance('image-name', project=GCE_PROJECT,
                             zone='us-central1-a')


def GenTests(api):
  yield api.test('basic')
