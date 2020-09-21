# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'src_state',
    'test_util',
]

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange


def RunSteps(api):
  # Using api.src_state.build_manifest
  # Initial values:
  api.assertions.assertEqual(api.src_state.external_manifest,
                             api.src_state.build_manifest)

  # Setting it works.
  api.src_state.build_manifest = api.src_state.internal_manifest
  api.assertions.assertEqual(api.src_state.internal_manifest,
                             api.src_state.build_manifest)

  # Setting it to None reverts to the original value.
  api.src_state.build_manifest = None
  api.assertions.assertEqual(api.src_state.external_manifest,
                             api.src_state.build_manifest)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
