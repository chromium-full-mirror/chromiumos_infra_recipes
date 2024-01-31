# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
]



def RunSteps(api):
  throttle_val = api.auto_retry_util.unthrottled_retries_left()
  api.assertions.assertEqual(api.properties['expected_throttle_value'],
                             throttle_val)


def GenTests(api):

  props = api.properties(**{
      '$chromeos/auto_retry_util': {
          'throttle_2hr': 30,
          'throttle_24hr': 300,
      }
  })

  def _recent_run_results(step_name, previous_retry_counts):

    def _build_result(bbid, retries):
      build = Build(id=bbid)
      build.output.properties.update({'retries_made': retries})
      return build

    ret = []
    for i, retries in enumerate(previous_retry_counts):
      ret.append(_build_result(i + 1, retries))
    return api.buildbucket.simulated_search_results(ret, step_name=step_name)

  yield api.test(
      'lots-of-recent-runs',
      props,
      # Short term.
      _recent_run_results('buildbucket.search', [15, 15]),
      # Long term.
      _recent_run_results('buildbucket.search (2)', [30, 20]),
      api.properties(expected_throttle_value=0),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'two-recent-runs',
      props,
      # Short term.
      _recent_run_results('buildbucket.search', [1, 1]),
      # Long term.
      _recent_run_results('buildbucket.search (2)', [1, 1]),
      api.properties(expected_throttle_value=28),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'lots-of-old-runs',
      props,
      # Short term.
      _recent_run_results('buildbucket.search', [1, 1]),
      # Long term.
      _recent_run_results('buildbucket.search (2)', [150, 149]),
      api.properties(expected_throttle_value=1),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'zero-recent-runs',
      props,
      api.properties(expected_throttle_value=30),
      api.post_process(post_process.DropExpectation),
  )
