# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  step_failures = []
  with api.step.nest('test1'):
    step_failures.append(api.step.StepFailure('test1 step failed'))

  summary_markdown = api.failures.format_step_failures(
      step_failures=step_failures)
  api.assertions.assertEqual(summary_markdown,
                             '1 step failed:\n\n\n- test1 step failed\n')


def GenTests(api):
  yield api.test('basic')
