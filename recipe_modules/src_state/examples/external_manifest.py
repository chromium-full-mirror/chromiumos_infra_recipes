# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'src_state',
    'test_util',
]

import os


def RunSteps(api):
  # Using api.src_state.external_manifest:
  external_manifest = api.src_state.external_manifest

  api.assertions.assertEqual(external_manifest.url, str(external_manifest))
  api.assertions.assertEqual(
      'https://chromium.googlesource.com/chromiumos/manifest',
      external_manifest.url)
  api.assertions.assertEqual(
      'manifest',
      os.path.relpath(
          str(external_manifest.path), str(api.src_state.workspace_path)))
  api.assertions.assertEqual('manifest', external_manifest.relpath)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
