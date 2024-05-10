# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the resize_lfg_lookback function."""

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.looks_for_green.tests.test import ResizeLfgLookbackProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'cros_history',
    'git_footers',
    'looks_for_green',
]

PROPERTIES = ResizeLfgLookbackProperties


def RunSteps(api, properties):
  example_change = GerritChange(
      host='test-host',
      change=1234,
      patchset=1,
  )

  api.looks_for_green.resize_lfg_lookback([example_change],
                                          ['arm64-generic-cq'])

  api.assertions.assertEqual(properties.expected_lookback_hours,
                             api.looks_for_green.lookback_hours)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(expected_lookback_hours=10),
      api.post_check(post_process.MustRun, 'resize LFG lookback window'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'depended-cls', api.properties(expected_lookback_hours=10),
      api.git_footers.simulated_get_footers(
          ['chromium:123'],
          'resize depended cls.check if all Cq-Depend CLs are included'),
      api.step_data(
          'resize depended cls.gerrit changes',
          api.json.output([{
              'submitted': '1969-01-01 12:00:00.000000000'
          }])), api.post_check(post_process.MustRun, 'resize depended cls'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'broken-until-snapshot',
      api.properties(expected_lookback_hours=10),
      api.buildbucket.simulated_multi_predicates_search_results(
          [api.cros_history.build_with_uprev_response(end_time=0)],
          step_name='resize broken until.buildbucket.search'),
      api.post_check(post_process.MustRun, 'resize broken until'),
      api.post_process(post_process.DropExpectation),
  )
