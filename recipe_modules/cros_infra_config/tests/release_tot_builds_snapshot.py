# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  expected_ref = api.properties['expected_ref'] or 'refs/heads/main'

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
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'release-tot-builds-snapshot-enabled-staging',
      api.buildbucket.try_build(
          experiments=[
              'chromeos.cros_infra_config.release_tot_builds_snapshot'
          ], project='chromeos', bucket='staging',
          builder='staging-release-main-orchestrator'),
      api.properties(expected_ref='refs/heads/staging-snapshot'),
      api.post_process(post_process.DropExpectation),
  )
