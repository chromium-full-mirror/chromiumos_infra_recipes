# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'build_menu',
    'cros_lkgm',
    'cros_infra_config',
    'cros_release',
    'test_util',
]



def RunSteps(api):
  api.cros_infra_config.configure_builder()

  api.cros_release.create_buildspec(
      gs_location='gs://chromeos-manifest-versions/buildspecs/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  build = api.cros_lkgm.schedule_public_build()
  api.assertions.assertTrue(api.cros_lkgm.has_public_build)
  is_staging = api.cros_infra_config.is_staging
  if is_staging:
    api.assertions.assertEqual(build.builder.builder,
                               'staging-public-main-orchestrator')
  else:
    api.assertions.assertEqual(build.builder.builder,
                               'public-main-orchestrator')
  api.cros_lkgm.collect_public_build()


def GenTests(api):
  yield api.test(
      'release-orchestrator',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
  )

  yield api.test(
      'staging-release-orchestrator',
      api.test_util.test_orchestrator(
          bucket='staging', builder='staging-release-main-orchestrator').build,
  )

  yield api.test(
      'no-builder-config',
      api.post_check(post_process.StepFailure, 'schedule public build'),
      status='FAILURE',
  )
