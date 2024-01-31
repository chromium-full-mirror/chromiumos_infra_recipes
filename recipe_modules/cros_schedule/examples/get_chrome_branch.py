# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'cros_schedule',
]



def RunSteps(api):
  api.cros_schedule.get_chrome_branch(112)


def GenTests(api):

  def override_fetch(ret_string):
    return api.step_data(
        'fetch chrome branch from chromiumdash.curl fetch_milestones',
        api.raw_io.stream_output(ret_string))

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-jq-return',
      override_fetch('not json'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'bad-jq-return',
      override_fetch('{}'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
