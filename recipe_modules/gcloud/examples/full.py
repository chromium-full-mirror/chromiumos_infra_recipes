# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'gcloud',
]


def RunSteps(api):
  api.gcloud.set_gce_project()
  api.gcloud.auth_list()
  api.gcloud.prep_image('chromeos-image-archive', 'image_path', 1234)
  api.gcloud.create_image('tar/path/1234.tar.gz', 'betty', 1234)
  api.gcloud.delete_image('image-name')
  api.gcloud.create_instance('image-name')
  api.gcloud.delete_instance('image-name')


def GenTests(api):
  yield api.test('basic')
