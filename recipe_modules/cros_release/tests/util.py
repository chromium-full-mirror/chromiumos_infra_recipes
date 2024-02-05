# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.chromiumos.common import CHANNEL_BETA, CHANNEL_STABLE
from PB.chromiumos.common import IMAGE_TYPE_BASE
from PB.chromiumos.common import IMAGE_TYPE_TEST_GUEST_VM
from PB.chromiumos.common import IMAGE_TYPE_FIRMWARE

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_release',
]



def RunSteps(api):
  api.cros_release.validate_sign_types()

  api.assertions.assertEqual(api.cros_release.channels,
                             [CHANNEL_BETA, CHANNEL_STABLE])
  api.assertions.assertEqual(api.cros_release.release_bucket,
                             'chromeos-releases')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'channels': [CHANNEL_BETA, CHANNEL_STABLE],
                  'sign_types': [IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE],
                  'release_bucket': 'chromeos-releases',
              }
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'unsupported-sign-type',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'channels': [CHANNEL_BETA, CHANNEL_STABLE],
                  'sign_types': [IMAGE_TYPE_TEST_GUEST_VM],
                  'release_bucket': 'chromeos-releases',
              }
          }), api.post_process(post_process.DropExpectation), status='FAILURE')
