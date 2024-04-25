# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.sdk_cache_state import SdkCacheState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'cros_sdk',
]



def RunSteps(api):
  workspace = api.path.cleanup_dir / 'workspace'

  with api.cros_sdk.cleanup_context(checkout_path=workspace):
    api.cros_sdk.configure(chroot_parent_path=api.path.cleanup_dir / 'test')
    api.assertions.assertEqual(api.cros_sdk.sdk_cache_state.version, 2)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('read sdk cache state json',
                    api.file.read_proto(SdkCacheState(version=2))))
