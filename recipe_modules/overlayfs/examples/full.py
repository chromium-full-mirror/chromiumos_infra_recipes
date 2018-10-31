# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'overlayfs',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  lowerdir_path = api.path['cache'].join('lowerdir')
  mount_path = api.path['start_dir'].join('mount')
  with api.overlayfs.context('mymount', lowerdir_path, mount_path):
    api.step('in mount', ['pwd'])


def GenTests(api):
  yield api.test('basic')
