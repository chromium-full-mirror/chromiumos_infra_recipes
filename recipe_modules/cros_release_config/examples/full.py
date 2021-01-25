# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_release_config',
    'repo',
]
from recipe_engine import post_process

EXPECTED_WRITE = """
  ...
  # Start of RELEASES
  RELEASES = [
      ('release-foo.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),

      ('release-R89-13729.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),

      ('release-R88-13597.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
  ]
  # End of RELEASES
  ...
"""

from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import (
    CrosReleaseConfigProperties)


def RunSteps(api):
  api.cros_release_config.update_config("release-foo.B")


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(reviewers=["jackneus@google.com"])
          }),
      api.post_process(post_process.StepCommandContains,
                       'update legacy config.write config/chromeos_config.py',
                       [EXPECTED_WRITE]))

  yield api.test(
      'no-reviewers',
      api.post_check(post_process.StepFailure, 'validate reviewers'),
  )
