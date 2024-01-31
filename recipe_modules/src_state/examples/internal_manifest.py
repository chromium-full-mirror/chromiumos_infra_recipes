# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'src_state',
    'test_util',
]



def RunSteps(api):
  # Using api.src_state.internal_manifest:
  internal_manifest = api.src_state.internal_manifest

  api.assertions.assertEqual(internal_manifest.url, str(internal_manifest))
  api.assertions.assertEqual(
      'https://chrome-internal.googlesource.com/chromeos/manifest-internal',
      internal_manifest.url)
  api.assertions.assertEqual('manifest-internal', internal_manifest.relpath)
  api.assertions.assertEqual(
      'manifest-internal',
      api.path.relpath(internal_manifest.path, api.src_state.workspace_path))

  # TODO(crbug/1152875): track branch name of manifest-internal ToT.
  api.assertions.assertEqual(
      GitilesCommit(host='chrome-internal.googlesource.com',
                    project='chromeos/manifest-internal',
                    ref='refs/heads/main'),
      internal_manifest.as_gitiles_commit_proto)

  api.assertions.assertNotEqual(internal_manifest,
                                api.src_state.external_manifest)
  api.assertions.assertEqual(api.src_state.test_api.default_branch,
                             api.src_state.default_branch)
  api.assertions.assertEqual(api.src_state.test_api.default_ref,
                             api.src_state.default_ref)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
