# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_release',
    'test_util',
]


def RunSteps(api):
  api.cros_release.push_and_sign_images()
  api.cros_release.schedule_payload_generation()


def GenTests(api):
  yield api.test('basic', api.test_util.test_child_build('amd64-generic').build)
