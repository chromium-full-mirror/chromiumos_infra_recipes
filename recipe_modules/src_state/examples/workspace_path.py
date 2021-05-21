# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'src_state',
    'test_util',
]


def RunSteps(api):
  workspace_path = api.src_state.workspace_path

  api.assertions.assertEqual(api.path['cleanup'].join('chromiumos_workspace'),
                             workspace_path)

  try:
    # workspace_path is immutable.
    api.src_state.workspace_path = 'foo'
  except AttributeError:
    pass


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
