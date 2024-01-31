# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'src_state',
    'test_util',
]



def RunSteps(api):

  external_manifest = api.src_state.external_manifest
  internal_manifest = api.src_state.internal_manifest

  api.assertions.assertEqual(
      api.src_state.manifest_projects,
      [internal_manifest.project, external_manifest.project])

  def _change(manifest):
    return GerritChange(host=manifest.host, project=manifest.project)

  # Using api.src_state.build_manifest
  # Initial values:
  bb_commit = api.buildbucket.gitiles_commit
  if bb_commit.host == external_manifest.host:
    want_manifest = external_manifest
    other_manifest = internal_manifest
    api.assertions.assertEqual(api.src_state.manifest_name, 'external')
  else:
    want_manifest = internal_manifest
    other_manifest = external_manifest
    api.assertions.assertEqual(api.src_state.manifest_name, 'internal')

  api.assertions.assertEqual(api.src_state.build_manifest.branch,
                             want_manifest.branch)

  api.assertions.assertEqual(want_manifest, api.src_state.build_manifest)
  api.assertions.assertTrue(
      _change(want_manifest) in api.src_state.build_manifest)
  api.assertions.assertFalse(
      _change(other_manifest) in api.src_state.build_manifest)
  api.assertions.assertEqual(
      want_manifest,
      api.src_state.gitiles_commit_to_manifest(bb_commit) or internal_manifest)
  if not bb_commit.host:
    api.assertions.assertIsNone(
        api.src_state.gitiles_commit_to_manifest(bb_commit))

  # Setting it to internal works.
  api.src_state.build_manifest = internal_manifest
  api.assertions.assertEqual(internal_manifest, api.src_state.build_manifest)
  api.assertions.assertEqual(api.src_state.manifest_name, 'internal')

  api.assertions.assertTrue(
      _change(internal_manifest) in api.src_state.build_manifest)
  api.assertions.assertFalse(
      _change(external_manifest) in api.src_state.build_manifest)

  # Setting it to external works.
  api.src_state.build_manifest = external_manifest
  api.assertions.assertEqual(external_manifest, api.src_state.build_manifest)
  api.assertions.assertEqual(api.src_state.manifest_name, 'external')

  api.assertions.assertFalse(
      _change(internal_manifest) in api.src_state.build_manifest)
  api.assertions.assertTrue(
      _change(external_manifest) in api.src_state.build_manifest)

  # Setting it to None reverts to the original value.
  api.src_state.build_manifest = None
  api.assertions.assertEqual(want_manifest, api.src_state.build_manifest)


def GenTests(api):
  yield api.test('basic', api.test_util.test_build(revision=None).build)

  yield api.test(
      'internal',
      api.test_util.test_build(
          git_repo=api.src_state.internal_manifest.url).build)

  yield api.test(
      'external',
      api.test_util.test_build(
          git_repo=api.src_state.external_manifest.url).build)
