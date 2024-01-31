# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'easy',
]


BUILD_WITH_PARENT_ID = build_pb2.Build()


def RunSteps(api: RecipeApi):
  api.easy.log_parent_step()


def GenTests(api: RecipeTestApi):
  PARENT_ID = 123456

  PARENT_BUILD_STEP = 'Parent build: {}'.format(PARENT_ID)
  NO_PARENT_BUILD_STEP = 'No parent build.'

  yield api.test(
      'with-parent',
      api.buildbucket.build(
          api.buildbucket.ci_build_message(
              tags=api.cros_tags.tags(parent_buildbucket_id=str(PARENT_ID)))),
      api.post_check(post_process.MustRun, PARENT_BUILD_STEP),
      api.post_check(post_process.DoesNotRun, NO_PARENT_BUILD_STEP),
  )

  yield api.test(
      'no-parent',
      api.buildbucket.build(api.buildbucket.ci_build_message()),
      api.post_check(post_process.MustRun, NO_PARENT_BUILD_STEP),
      api.post_check(post_process.DoesNotRun, PARENT_BUILD_STEP),
  )
