#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git',
]



def RunSteps(api):
  with api.step.nest('single remote'):
    api.assertions.assertEqual(api.git.remote(), 'origin')

  with api.step.nest('multiple remotes'):
    with api.assertions.assertRaises(StepFailure):
      api.git.remote()


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('single remote.git remote',
                    stdout=api.raw_io.output_text('origin\n')),
      api.step_data('multiple remotes.git remote',
                    stdout=api.raw_io.output_text('origin\ncros\n')))
