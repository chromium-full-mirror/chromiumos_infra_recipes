# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test case for ManifestProject.__hash__()."""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'src_state',
]



def RunSteps(api):
  HOST, HOST2 = 'my_host', 'my_host2'
  PROJECT, PROJECT2 = 'my_project', 'my_project2'
  REL_PATH, REL_PATH2 = 'my_rel_path', 'my_rel_path2'
  tmpdir = api.path.mkdtemp()
  WORKSPACE_PATH, WORKSPACE_PATH2 = (tmpdir / 'my_workspace_path',
                                     tmpdir / 'my_workspace_path2')
  REF, REF2 = 'my_ref', 'my_ref2'
  GERRIT_HOST, GERRIT_HOST2 = 'my_gerrit_host', 'my_gerrit_host2'

  # Two equivalent ManifestProjects should have equal hashes.
  mp1 = api.src_state.ManifestProject(HOST, PROJECT, REL_PATH, WORKSPACE_PATH,
                                      ref=REF, gerrit_host=GERRIT_HOST)
  mp2 = api.src_state.ManifestProject(HOST, PROJECT, REL_PATH, WORKSPACE_PATH,
                                      ref=REF, gerrit_host=GERRIT_HOST)
  api.assertions.assertEqual(mp1, mp2)
  api.assertions.assertEqual(hash(mp1), hash(mp2))

  # Changing any input param should change the hash.
  for mp3 in [
      api.src_state.ManifestProject(HOST2, PROJECT, REL_PATH, WORKSPACE_PATH,
                                    ref=REF, gerrit_host=GERRIT_HOST),
      api.src_state.ManifestProject(HOST, PROJECT2, REL_PATH, WORKSPACE_PATH,
                                    ref=REF, gerrit_host=GERRIT_HOST),
      api.src_state.ManifestProject(HOST, PROJECT, REL_PATH2, WORKSPACE_PATH,
                                    ref=REF, gerrit_host=GERRIT_HOST),
      api.src_state.ManifestProject(HOST, PROJECT, REL_PATH, WORKSPACE_PATH2,
                                    ref=REF, gerrit_host=GERRIT_HOST),
      api.src_state.ManifestProject(HOST, PROJECT, REL_PATH, WORKSPACE_PATH,
                                    ref=REF2, gerrit_host=GERRIT_HOST),
      api.src_state.ManifestProject(HOST, PROJECT, REL_PATH, WORKSPACE_PATH,
                                    ref=REF, gerrit_host=GERRIT_HOST2),
  ]:
    api.assertions.assertNotEqual(mp1, mp3)
    api.assertions.assertNotEqual(hash(mp1), hash(mp3))

  # Being hashable, ManifestProjects should be insertable into sets
  set([mp1])


def GenTests(api):
  yield api.test('basic')
