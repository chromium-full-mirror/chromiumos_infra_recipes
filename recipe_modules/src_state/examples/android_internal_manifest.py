# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for functions related to the Android internal manifest."""

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'src_state',
    'test_util',
]


def RunSteps(api):
  android_internal_manifest = api.src_state.android_internal_manifest

  api.assertions.assertEqual(android_internal_manifest.url,
                             str(android_internal_manifest))
  api.assertions.assertEqual(
      'https://googleplex-android.googlesource.com/platform/manifest',
      android_internal_manifest.url)
  api.assertions.assertEqual(None, android_internal_manifest.relpath)

  api.assertions.assertEqual(
      GitilesCommit(host='googleplex-android.googlesource.com',
                    project='platform/manifest', ref='refs/heads/main'),
      android_internal_manifest.as_gitiles_commit_proto)

  api.assertions.assertEqual(api.src_state.test_api.default_branch,
                             api.src_state.default_branch)
  api.assertions.assertEqual(api.src_state.test_api.default_ref,
                             api.src_state.default_ref)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build().build)
