# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_schedule.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'cros_schedule',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  kwargs = {}
  if properties.fetch_n:
    kwargs['fetch_n'] = properties.fetch_n
  if properties.start_mstone:
    kwargs['start_mstone'] = properties.start_mstone
  api.cros_schedule.fetch_chromiumdash_schedule(**kwargs)


def GenTests(api):

  def override_fetch(ret_string):
    return api.step_data(
        'fetch chromiumdash schedule.curl fetch_milestone_schedule',
        api.raw_io.stream_output(ret_string))

  # Seed recent time Friday, February 19, 2021 12:30:23 AM for test data.
  yield api.test('basic', api.time.seed(1613694623.0))

  # Start as if you were querying in the past (before 88) to cover exception.
  yield api.test(
      'back-to-the-future',
      api.time.seed(1513694623.0),
      status='FAILURE',
  )

  yield api.test(
      'not-jq-return',
      override_fetch('not json'),
      status='FAILURE',
  )

  yield api.test(
      'bad-jq-return',
      override_fetch('{}'),
      status='FAILURE',
  )

  yield api.test(
      'fetch-one',
      api.properties(start_mstone=88, fetch_n=1),
      override_fetch(
          api.cros_schedule.test_chromiumdash_fetch_response(
              fetch_n=1, ltr_last_refresh_date='2023-01-01T00:00:00')),
  )

  yield api.test(
      'fetch-too-few',
      api.properties(start_mstone=88, fetch_n=2),
      override_fetch(
          api.cros_schedule.test_chromiumdash_fetch_response(fetch_n=1)),
      status='FAILURE',
  )
