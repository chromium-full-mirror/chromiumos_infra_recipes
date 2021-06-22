# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_source',
    'src_state',
]

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.cros_source.examples.configure_builder import (
    ConfigureBuilderProperties)

PROPERTIES = ConfigureBuilderProperties


def RunSteps(api, properties):

  api.cros_source.configure_builder()
  api.assertions.assertEqual(api.src_state.gitiles_commit,
                             properties.expected_gitiles_commit)


def GenTests(api):

  manifest = api.src_state.internal_manifest
  snapshot = manifest.as_gitiles_commit_proto
  snapshot.ref = 'refs/heads/snapshot'
  snapshot.id = 'snapshot-HEAD-SHA'

  # Commit provided in buildbucket
  yield api.cros_source.test(
      'provided',
      api.properties(
          ConfigureBuilderProperties(expected_gitiles_commit=snapshot)),
      api.post_check(post_process.StatusSuccess), git_repo=manifest.url,
      git_ref=snapshot.ref, revision=snapshot.id, cq=True)

  yield api.cros_source.test('snapshot',
                             api.properties(expected_gitiles_commit=snapshot),
                             api.post_check(post_process.StatusSuccess),
                             git_repo=None, git_ref=None, revision=None,
                             cq=True)
