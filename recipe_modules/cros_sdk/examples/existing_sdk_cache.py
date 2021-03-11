# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'cros_sdk',
]

from PB.chromiumos.sdk_cache_state import SdkCacheState


def RunSteps(api):
  workspace = api.path['cleanup'].join('workspace')

  with api.cros_sdk.cleanup_context(checkout_path=workspace):
    api.cros_sdk.configure(chroot_parent_path=api.path['cleanup'].join('test'))
    api.assertions.assertEqual(api.cros_sdk.sdk_cache_state.version, 2)

    api.cros_sdk._write_sdk_cache_state(version=3)
    api.assertions.assertEqual(api.cros_sdk.sdk_cache_state.version, 3)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('read sdk cache state json',
                    api.file.read_proto(SdkCacheState(version=2))))
