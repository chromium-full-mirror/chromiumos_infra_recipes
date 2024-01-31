# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'cros_sdk',
]



# pylint: disable=protected-access
def RunSteps(api):
  with api.cros_sdk.cleanup_context():
    api.cros_sdk._check_sdk_cache_state(version=1)


def GenTests(api):

  yield api.test(
      'named-cache-sdk-valid',
      api.cros_sdk.is_chroot_usable([True]),
      api.post_check(post_process.PropertyEquals, 'sdk_cache', 'cros_chroot'),
      api.post_check(post_process.MustRun, 'check SDK in named cache'),
  )
