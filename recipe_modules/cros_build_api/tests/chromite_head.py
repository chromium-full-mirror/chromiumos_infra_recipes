# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from typing import Generator

from PB.chromite.api import artifacts
from PB.chromiumos.common import BuildTarget
from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {'use_chromite_head': Property(default=False)}


def RunSteps(api: RecipeApi, use_chromite_head: bool) -> None:
  input_proto = artifacts.BundleRequest(build_target=BuildTarget(name='target'))
  api.cros_build_api.ArtifactsService.BundleFirmware(
      input_proto, use_chromite_head=use_chromite_head)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  yield api.test(
      'basic',
      api.post_process(
          post_process.StepCommandContains,
          'call chromite.api.ArtifactsService/BundleFirmware.call build API script',
          ['[CLEANUP]/chromiumos_workspace/chromite/bin/build_api']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'use_chromite_head',
      api.properties(use_chromite_head=True),
      api.post_process(
          post_process.StepCommandContains,
          'call chromite.api.ArtifactsService/BundleFirmware.call build API script',
          ['[CLEANUP]/chromiumos_workspace/infra/chromite-HEAD/bin/build_api']),
      api.post_process(post_process.DropExpectation),
  )
