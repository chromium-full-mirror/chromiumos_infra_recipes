# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_release',
    'test_util',
]

from recipe_engine import post_process
from PB.recipe_modules.chromeos.cros_version.cros_version import CrosVersionProperties


def RunSteps(api):
  api.cros_release.push_and_sign_images()
  api.cros_release.schedule_payload_generation()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
          }),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request',
          ['gs://chromeos-image-archive/amd64-generic-release/R99-1234.56.0']),
      api.test_util.test_child_build('amd64-generic').build)
