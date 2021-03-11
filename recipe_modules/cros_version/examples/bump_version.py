# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/file',
    'cros_infra_config',
    'cros_version',
]

from recipe_engine import post_process


def RunSteps(api):
  api.cros_version.bump_version()


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='main-release-orchestrator',
      ),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['chromiumos/infra/version_bumper/${platform} prod']),
  )

  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='staging-main-release-orchestrator',
      ),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['chromiumos/infra/version_bumper/${platform} staging']),
  )

  yield api.test(
      'with-ref',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='main-release-orchestrator',
      ),
      api.properties(
          **{
              "$chromeos/cros_version": {
                  "version_bumper_cipd_package": "version_bumper_foo",
                  "version_bumper_cipd_ref": "bar",
              }
          }),
      api.post_check(post_process.StepCommandContains,
                     'bump version.ensure version_bumper.ensure_installed',
                     ['version_bumper_foo bar']),
  )
