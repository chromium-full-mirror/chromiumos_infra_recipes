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
  instance = api.gcloud.create_instance()
  api.gcloud.delete_instance(instance)


def GenTests(api):
  yield api.test('basic')
