# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for various `gobin` module failure modes."""

from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/step',
    'gobin',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: recipe_api.RecipeApi):
  with api.assertions.assertRaises(StepFailure):
    api.gobin.ensure_package('bad_package')
  api.gobin.ensure_package('my_gobin')


def GenTests(api: recipe_api.RecipeApi):
  yield api.test(
      'wrong-json',
      api.step_data(
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef.read [CLEANUP]/cipd.json',
          api.file.read_text('{}')),
      api.post_check(post_process.MustRun,
                     'ensure my_gobin.read infrainfra golang version'),
      api.post_check(
          post_process.LogContains,
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef',
          'exception', ['KeyError']),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'invalid-json',
      api.step_data(
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef.read [CLEANUP]/cipd.json',
          api.file.read_text('{')),
      api.post_check(
          post_process.LogContains,
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef',
          'exception', ['JSONDecodeError']),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  CIPD_JSON_DIFFERENT_PACKAGE = '''{
    "result": [
        {
            "package": "chromiumos/infra/manifest_doctor/linux-amd64",
            "instance_id": "wzCA5zCcIkg0uYroNN91fpH1oQLMVHYaXM8RS9SuQwUC"
        }
    ]
}
'''

  yield api.test(
      'missing-package',
      api.step_data(
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef.read [CLEANUP]/cipd.json',
          api.file.read_text(CIPD_JSON_DIFFERENT_PACKAGE)),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
