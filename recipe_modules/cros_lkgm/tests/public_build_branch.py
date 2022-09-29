# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_lkgm',
    'cros_infra_config',
    'cros_release',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = {
    'expected_ref':
        Property(kind=str, help='The expected orchestrator gitiles ref.',
                 default='refs/heads/main'),
    'expected_builder':
        Property(kind=str, help='The expected builder name.',
                 default='public-main-orchestrator'),
}


def RunSteps(api, expected_ref, expected_builder):
  config = api.cros_infra_config.configure_builder()

  api.cros_release.create_buildspec(
      gs_location='gs://chromeos-manifest-versions/buildspecs/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  build = api.cros_lkgm.schedule_public_build()

  api.assertions.assertEqual(expected_builder, build.builder.builder)
  api.assertions.assertEqual(expected_ref,
                             config.orchestrator.gitiles_commit.ref)


def GenTests(api):
  yield api.test(
      'main-branch',
      api.test_util.test_orchestrator(
          experiments=[
              'chromeos.cros_infra_config.release_tot_builds_snapshot'
          ], bucket='release', builder='release-main-orchestrator').build,
      api.properties(expected_ref='refs/heads/snapshot'),
      api.properties(expected_builder='public-main-orchestrator'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging-main-branch',
      api.test_util.test_orchestrator(
          experiments=[
              'chromeos.cros_infra_config.release_tot_builds_snapshot'
          ], bucket='staging',
          builder='staging-release-main-orchestrator').build,
      api.properties(expected_ref='refs/heads/staging-snapshot'),
      api.properties(expected_builder='staging-public-main-orchestrator'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
