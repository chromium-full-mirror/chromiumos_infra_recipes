# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_sdk.cros_sdk import CrosSdkProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


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
      api.post_check(post_process.DoesNotRun, 'check SDK in preload cache'),
  )

  yield api.test(
      'preload-sdk-valid-mount-experiment-on',
      api.cros_sdk.is_chroot_usable([False, True]),
      api.properties(
          **{"$chromeos/cros_sdk": CrosSdkProperties(mount_named_cache=True)}),
      api.post_check(post_process.PropertyEquals, 'sdk_cache', 'preload'),
      api.post_check(post_process.MustRun, 'check SDK in named cache'),
      api.post_check(post_process.MustRun, 'check SDK in preload cache'),
      api.post_check(post_process.MustRun,
                     'check SDK in preload cache.delete SDK in named cache'),
  )

  yield api.test(
      'preload-sdk-valid-mount-experiment-off',
      api.cros_sdk.is_chroot_usable([False]),
      api.post_check(post_process.PropertyEquals, 'sdk_cache', 'none'),
      api.post_check(post_process.MustRun, 'check SDK in named cache'),
      api.post_check(post_process.DoesNotRun, 'check SDK in preload cache'),
      api.post_check(post_process.DoesNotRun,
                     'check SDK in preload cache.delete SDK in named cache'),
  )

  yield api.test(
      'no-valid-sdk-mount-experiment-on',
      api.cros_sdk.is_chroot_usable([False, False]),
      api.properties(
          **{"$chromeos/cros_sdk": CrosSdkProperties(mount_named_cache=True)}),
      api.post_check(post_process.PropertyEquals, 'sdk_cache', 'none'),
      api.post_check(post_process.MustRun, 'check SDK in named cache'),
      api.post_check(post_process.MustRun, 'check SDK in preload cache'),
      api.post_check(post_process.DoesNotRun,
                     'check SDK in preload cache.delete SDK in named cache'),
  )

  yield api.test(
      'no-valid-sdk-mount-experiment-off',
      api.cros_sdk.is_chroot_usable([False]),
      api.post_check(post_process.PropertyEquals, 'sdk_cache', 'none'),
      api.post_check(post_process.MustRun, 'check SDK in named cache'),
      api.post_check(post_process.DoesNotRun, 'check SDK in preload cache'),
      api.post_check(post_process.DoesNotRun,
                     'check SDK in preload cache.delete SDK in named cache'),
  )

  yield api.test(
      'no-valid-sdk-mount-preload-does-not-exist',
      api.cros_sdk.is_chroot_usable([False]),
      api.cros_sdk.preload_path_exists(False),
      api.post_check(post_process.PropertyEquals, 'sdk_cache', 'none'),
      api.post_check(post_process.MustRun, 'check SDK in named cache'),
      api.post_check(post_process.DoesNotRun, 'check SDK in preload cache'),
      api.post_check(post_process.DoesNotRun,
                     'check SDK in preload cache.delete SDK in named cache'),
  )
