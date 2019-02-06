# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/file',
    'cros_test'
]


def RunSteps(api):
  api.file.ensure_directory('ensure image path', api.cros_test.image_path)
  api.cros_test.run_vm_test('build_target', 'test_suite')


def GenTests(api):
  yield api.test('basic')
