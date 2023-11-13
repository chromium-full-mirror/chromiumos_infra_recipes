# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test that a gobin that hasn't been enabled falls back to the legacy label."""

from recipe_engine import post_process
from recipe_engine import recipe_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/step',
    'gobin',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: recipe_api.RecipeApi):
  api.gobin.ensure_package('chromiumos/infra/my_other_gobin/${platform}')


def GenTests(api: recipe_api.RecipeApi):
  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='staging-release-main-orchestrator',
      ),
      api.post_check(post_process.DoesNotRun,
                     'ensure my_other_gobin.read infrainfra golang version'),
      api.post_check(post_process.StepCommandContains,
                     'ensure my_other_gobin.ensure_installed',
                     ['chromiumos/infra/my_other_gobin/${platform} staging']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'prod',
      api.post_check(post_process.DoesNotRun,
                     'ensure my_other_gobin.read infrainfra golang version'),
      api.post_check(post_process.StepCommandContains,
                     'ensure my_other_gobin.ensure_installed',
                     ['chromiumos/infra/my_other_gobin/${platform} prod']),
      api.post_process(post_process.DropExpectation),
  )
