# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.sdk_cache_state import SdkCacheState

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_sdk',
    'git',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = {
    'is_chroot_usable': Property(default=False),
}


# pylint: disable=protected-access
def RunSteps(api, is_chroot_usable):
  with api.step.nest('is chroot usable') as parent_step:
    reuse = api.cros_sdk._is_chroot_usable(api.cros_sdk.sdk_cache_state,
                                           version=1,
                                           step_logs=parent_step.logs)
    api.assertions.assertEqual(is_chroot_usable, reuse)


def GenTests(api):

  def _sdk_cache_state_file(version=1,
                            manifest_url=api.src_state.internal_manifest.url,
                            manifest_branch='snapshot', snapshot_hash=''):
    return SdkCacheState(version=version, manifest_url=manifest_url,
                         manifest_branch=manifest_branch,
                         snapshot_hash=snapshot_hash)

  yield api.test(
      'reusable',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(snapshot_hash='123\n'))),
      api.properties(is_chroot_usable=True))

  yield api.test(
      'mismatch-version',
      api.step_data('is chroot usable.read sdk cache state json',
                    api.file.read_proto(_sdk_cache_state_file(version=2))))

  yield api.test(
      'mismatch-url',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(manifest_url='other'))))

  yield api.test(
      'mismatch-branch',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(manifest_branch='other'))))

  yield api.test(
      'mismatch-snapshot-hash',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(snapshot_hash='123\n'))),
      api.git.is_reachable(False))
