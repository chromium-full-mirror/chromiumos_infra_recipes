# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_schedule',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_schedule.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  args = {}
  if properties.fetch_n:
    args['fetch_n'] = properties.fetch_n
  if properties.start_mstone:
    args['start_mstone'] = properties.start_mstone
  api.cros_schedule._fetch_chromiumdash_schedule(**args)


def GenTests(api):

  def override_fetch(ret_string):
    return api.step_data(
        'fetch chromiumdash schedule.curl fetch_milestone_schedule',
        api.raw_io.stream_output(ret_string))

  yield api.test('basic')

  yield api.test('not-jq-return', override_fetch('not json'),
                 api.post_check(post_process.StatusFailure))

  yield api.test('bad-jq-return', override_fetch('{}'),
                 api.post_check(post_process.StatusFailure))

  yield api.test(
      'fetch-one', api.properties(start_mstone=88, fetch_n=1),
      override_fetch(
          api.cros_schedule.test_chromiumdash_fetch_response(n_stones=1)),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'fetch-too-few', api.properties(start_mstone=88, fetch_n=2),
      override_fetch(
          api.cros_schedule.test_chromiumdash_fetch_response(n_stones=1)),
      api.post_check(post_process.StatusFailure))
