# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.chromiumos.common import IMAGE_TYPE_BASE
from PB.chromiumos.common import IMAGE_TYPE_TEST_GUEST_VM
from PB.chromiumos.common import IMAGE_TYPE_FIRMWARE

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_release',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_release.validate_sign_types()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'sign_types': [IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE],
              }
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'unsupported',
      api.properties(**{
          '$chromeos/cros_release': {
              'sign_types': [IMAGE_TYPE_TEST_GUEST_VM],
          }
      }), api.post_process(post_process.DropExpectation), status='FAILURE')
