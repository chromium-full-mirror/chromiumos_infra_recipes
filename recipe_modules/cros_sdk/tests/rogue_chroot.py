# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'cros_sdk',
]

def RunSteps(api):
  workspace = api.path['cleanup'].join('workspace')

  with api.cros_sdk.cleanup_context(checkout_path=workspace):
    chroot = workspace.join('chroot')
    api.file.ensure_directory('create chroot dir', chroot)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data(
          'clean up SDK chroot.unlink chroot in workspace.'
          'remove original chroot link', retcode=1))
