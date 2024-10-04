# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for uprev and push packages."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'cros_source',
    'src_state',
]


def RunSteps(api: RecipeApi):
  api.cros_source.uprev_and_push_packages()


def GenTests(api: RecipeTestApi):
  yield api.test(
      'success',
      api.post_check(post_process.MustRun,
                     'uprev and push packages.uprev packages'),
      api.post_check(post_process.MustRun,
                     'uprev and push packages.push uprevs'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'uprev-fails',
      api.step_data(
          'uprev and push packages.uprev packages.call chromite.api.PackageService/Uprev.call build API script',
          retcode=1),
      api.post_check(post_process.MustRun,
                     'uprev and push packages.uprev packages'),
      api.post_check(post_process.DoesNotRun,
                     'uprev and push packages.push uprevs'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'push-fails',
      api.step_data(
          'uprev and push packages.push uprevs.push to src/overlay.git push src/overlay',
          retcode=1),
      api.post_check(post_process.MustRun,
                     'uprev and push packages.uprev packages'),
      api.post_check(post_process.MustRun,
                     'uprev and push packages.push uprevs'),
      api.post_process(post_process.DropExpectation),
  )
