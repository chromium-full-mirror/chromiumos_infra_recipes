# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_lkgm.tests.public_build_branch import \
  PublicBuildBranchProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_lkgm',
    'cros_infra_config',
    'cros_release',
    'test_util',
]


PROPERTIES = PublicBuildBranchProperties


def RunSteps(api, properties):
  expected_ref = properties.expected_ref or 'refs/heads/main'
  expected_builder = properties.expected_builder or 'public-main-orchestrator'

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
          bucket='release', builder='release-main-orchestrator').build,
      api.properties(expected_ref='refs/heads/snapshot'),
      api.properties(expected_builder='public-main-orchestrator'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging-main-branch',
      api.test_util.test_orchestrator(
          bucket='staging', builder='staging-release-main-orchestrator').build,
      api.properties(expected_ref='refs/heads/staging-snapshot'),
      api.properties(expected_builder='staging-public-main-orchestrator'),
      api.post_process(post_process.DropExpectation),
  )
