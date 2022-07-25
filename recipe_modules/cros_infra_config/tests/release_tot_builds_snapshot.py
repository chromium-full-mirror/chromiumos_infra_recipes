# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = {
    'expected_ref':
        Property(kind=str, help='The expected orchestrator gitiles ref.',
                 default='refs/heads/main')
}


def RunSteps(api, expected_ref):

  commit = api.buildbucket.gitiles_commit
  config = api.cros_infra_config.configure_builder(commit=commit, changes=None)
  api.assertions.assertEqual(expected_ref,
                             config.orchestrator.gitiles_commit.ref)


def GenTests(api):
  yield api.test(
      'release-tot-builds-snapshot-not-enabled',
      api.buildbucket.try_build(project='chromeos', bucket='release',
                                builder='release-main-orchestrator'),
      api.properties(expected_ref='refs/heads/main'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'release-tot-builds-snapshot-enabled',
      api.buildbucket.try_build(
          experiments=[
              'chromeos.cros_infra_config.release_tot_builds_snapshot'
          ], project='chromeos', bucket='release',
          builder='release-main-orchestrator'),
      api.properties(expected_ref='refs/heads/snapshot'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'release-tot-builds-snapshot-enabled-staging',
      api.buildbucket.try_build(
          experiments=[
              'chromeos.cros_infra_config.release_tot_builds_snapshot'
          ], project='chromeos', bucket='staging',
          builder='staging-release-main-orchestrator'),
      api.properties(expected_ref='refs/heads/staging-snapshot'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
