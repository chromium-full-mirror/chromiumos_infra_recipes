# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'cros_sdk',
]


def RunSteps(api):
  api.cros_sdk.configure(chroot_parent_path=api.path['cleanup'].join('test'))
  api.cros_sdk('get cros_sdk help', ['--help'])
  api.cros_sdk.run('ls in chroot', ['ls'], env={'PATH': '/bin'})


def GenTests(api):
  yield api.test('basic')
