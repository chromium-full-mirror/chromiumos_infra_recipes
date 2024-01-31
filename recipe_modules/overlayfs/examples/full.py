# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'overlayfs',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]



def RunSteps(api):
  lowerdir_path = api.path['cache'].join('lowerdir')
  mount_a = api.path['start_dir'].join('mount_a')
  mount_b = api.path['start_dir'].join('mount_b')
  mount_c = api.path['start_dir'].join('mount_c')

  # Multiple mounts
  with api.overlayfs.cleanup_context():
    api.overlayfs.mount('a', lowerdir_path, mount_a, persist=True)
    api.overlayfs.mount('b', lowerdir_path, mount_b)
    api.overlayfs.mount('c', lowerdir_path, mount_c)

  # Nested mount contexts
  with api.overlayfs.cleanup_context():
    api.overlayfs.mount('a', lowerdir_path, mount_a)
    with api.overlayfs.cleanup_context():
      with api.overlayfs.cleanup_context():
        api.overlayfs.mount('b', lowerdir_path, mount_b)
      api.overlayfs.mount('c', lowerdir_path, mount_c)

  # Cleanup workdirs
  api.overlayfs.cleanup_overlay_directories(cache_name='mount_a')

  # Empty context
  with api.overlayfs.cleanup_context():
    pass

  # Unmount warning
  api.overlayfs.unmount('fake', api.path['start_dir'].join('fake'))


def GenTests(api):
  yield api.test('basic')
  yield api.test(
      'random-work-path',
      api.properties(**{'$chromeos/overlayfs': {
          'random_work_path': True
      }}))
  yield api.test(
      'unmount-exceptions-swallowed',
      api.step_data('clean up overlayfs mounts.unmount overlay b', retcode=1))
