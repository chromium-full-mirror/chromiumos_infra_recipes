# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'src_state',
]



def RunSteps(api):
  try:
    api.src_state.test_api.ManifestProject.by_name(
        'foo', api.src_state.test_api.workspace_path)
  except KeyError:
    pass

  manifest = api.src_state.internal_manifest
  test_manifest = api.src_state.test_api.internal_manifest
  api.assertions.assertEqual(manifest.url, test_manifest.url)

  manifest = api.src_state.external_manifest
  test_manifest = api.src_state.test_api.external_manifest
  api.assertions.assertEqual(manifest, test_manifest)


def GenTests(api):

  yield api.test('bad-manifest-name')
