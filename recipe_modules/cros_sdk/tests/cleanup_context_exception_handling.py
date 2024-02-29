# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests exception handling in the cleanup_context."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/step',
    'cros_sdk',
]


def RunSteps(api):
  with api.cros_sdk.cleanup_context():
    api.step('A test step with retcode', cmd=['echo', 'hello world'])


def GenTests(api):

  yield api.test(
      'no-exceptions',
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  yield api.test(
      'exception-in-recipe',
      api.step_data('A test step with retcode', retcode=1),
      api.post_process(post_process.SummaryMarkdown,
                       "Step('A test step with retcode') (retcode: 1)"),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  sdk_delete_step = (
      'clean up SDK chroot.ensure no rogue SDK.'
      'call chromite.api.SdkService/Delete.call build API script')
  yield api.test(
      'exception-in-cleanup',
      api.step_data(sdk_delete_step, retcode=1),
      api.post_process(post_process.SummaryMarkdown,
                       f"Step('{sdk_delete_step}') (retcode: 1)"),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'exception-in-recipe-and-cleanup-prefer-recipe-exception',
      api.step_data('A test step with retcode', retcode=1),
      api.step_data(sdk_delete_step, retcode=1),
      api.post_process(post_process.SummaryMarkdown,
                       "Step('A test step with retcode') (retcode: 1)"),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
