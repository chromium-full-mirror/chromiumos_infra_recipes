# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.sdk_cache_state import SdkCacheState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_sdk',
    'git',
    'git_footers',
    'src_state',
]


# pylint: disable=protected-access
def RunSteps(api):
  with api.step.nest('is chroot usable') as parent_step:
    reuse = api.cros_sdk._is_chroot_usable(api.cros_sdk.sdk_cache_state,
                                           version=1,
                                           step_presentation=parent_step)
    api.assertions.assertEqual(api.properties['is_chroot_usable'], reuse)


def GenTests(api):

  def _sdk_cache_state_file(version=1,
                            manifest_url=api.src_state.internal_manifest.url,
                            manifest_branch='snapshot', snapshot_hash='123\n'):
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
      'no-cached-sdk',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(snapshot_hash=''))),
      api.properties(is_chroot_usable=False), api.git.is_reachable(False))

  yield api.test(
      'mismatch-version',
      api.step_data('is chroot usable.read sdk cache state json',
                    api.file.read_proto(_sdk_cache_state_file(version=2))),
      api.properties(is_chroot_usable=False))

  yield api.test(
      'mismatch-url',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(manifest_url='other'))),
      api.properties(is_chroot_usable=False))

  yield api.test(
      'mismatch-branch',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(manifest_branch='other'))),
      api.properties(is_chroot_usable=False))

  yield api.test(
      'no-external-snapshot-commit',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(
              _sdk_cache_state_file(
                  manifest_branch='snapshot',
                  manifest_url=api.src_state.external_manifest.url))),
      api.git_footers.simulated_get_footers([], 'is chroot usable'),
      api.git.is_reachable(False), api.properties(is_chroot_usable=False))

  yield api.test(
      'external-sdk-not-reusable-by-internal-build',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(
              _sdk_cache_state_file(
                  manifest_branch='snapshot',
                  manifest_url=api.src_state.external_manifest.url))),
      api.git.is_reachable(False), api.properties(is_chroot_usable=False))

  yield api.test(
      'external-sdk-reusable-by-internal-build',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(
              _sdk_cache_state_file(
                  manifest_branch='snapshot',
                  manifest_url=api.src_state.external_manifest.url))),
      api.properties(is_chroot_usable=True))

  yield api.test(
      'mismatch-snapshot-hash',
      api.step_data(
          'is chroot usable.read sdk cache state json',
          api.file.read_proto(_sdk_cache_state_file(snapshot_hash='123\n'))),
      api.git.is_reachable(False), api.properties(is_chroot_usable=False))
