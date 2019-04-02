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

  api.cros_sdk('get cros_sdk help', ['--help'])
  api.cros_sdk.run('ls in chroot', ['ls'], env={'PATH': '/bin'},
                   workspace=workspace,
                   chrome_root=api.path['cleanup'].join('chrome_root_test'))

  workspace_file = workspace.join('inner', 'file')
  chroot_path = api.cros_sdk.workspace_path_to_chroot(workspace, workspace_file)
  assert chroot_path == '/mnt/host/workspace/inner/file'


def GenTests(api):
  yield api.test('basic')
