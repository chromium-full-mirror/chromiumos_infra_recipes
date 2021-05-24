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
GCE_PROJECT = 'chromeos-gce-tests'


def RunSteps(api):
  api.gcloud.set_gce_project(project=GCE_PROJECT)
  api.gcloud.auth_list()
  api.random.seed(int(api.time.time()))
  rand_id = api.random.randint(1000000, 9999999)
  tar_path = api.gcloud.prep_image(TEMP_GS_BUCKET, TEMP_GS_PATH, rand_id)
  image = api.gcloud.create_image(tar_path, 'betty-arc-r', rand_id)
  api.gcloud.create_instance(image, project=GCE_PROJECT,
                             machine='n1-standard-4', zone='us-central1-a',
                             network='chromeos-gce-tests', subnet='us-central1')
  api.gcloud.delete_instance(image, project=GCE_PROJECT, zone='us-central1-a')
  api.gcloud.delete_image(image)


def GenTests(api):
  yield api.test('basic')
