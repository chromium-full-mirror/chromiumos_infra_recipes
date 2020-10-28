# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running GCE tests."""

DEPS = [
    'gcloud',
    'recipe_engine/random',
    'recipe_engine/time',
]

TEMP_GS_BUCKET = 'chromeos-image-archive'
TEMP_GS_PATH = 'betty-arc-r-snapshot/R88-13550.0.0-39788-8865622468216306576/'


def RunSteps(api):
  api.gcloud.set_gce_project()
  api.gcloud.auth_list()
  api.random.seed(int(api.time.time()))
  rand_id = api.random.randint(1000000, 9999999)
  tar_path = api.gcloud.prep_image(TEMP_GS_BUCKET, TEMP_GS_PATH, rand_id)
  image = api.gcloud.create_image(tar_path, 'betty-arc-r', rand_id)
  api.gcloud.create_instance(image)
  api.gcloud.delete_instance(image)
  api.gcloud.delete_image(image)


def GenTests(api):
  yield api.test('basic')
