# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'cros_sdk',
]


def RunSteps(api):
  workspace = api.path['cleanup'].join('workspace')

  api.cros_sdk.configure(chroot_parent_path=api.path['cleanup'].join('test'))
  api.assertions.assertTrue(
      api.cros_sdk.chroot.path.endswith('test/cros_chroot'))

  api.cros_sdk('get cros_sdk help', ['--help'])
  api.cros_sdk.run('ls in chroot', ['ls'], env={'PATH': '/bin'},
                   workspace=workspace)

  api.cros_sdk.link_chroot(api.path['cleanup'].join('checkout'))

  # Link a second time to handle case where link exists.
  api.cros_sdk.link_chroot(api.path['cleanup'].join('checkout'))


def GenTests(api):
  yield api.test('basic')
