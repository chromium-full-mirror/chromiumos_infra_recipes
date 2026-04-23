# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the should_lfg function."""

from recipe_engine import post_process
from RECIPE_MODULES.chromeos.looks_for_green.test_api import LooksStatusEquals

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus
from PB.recipe_modules.chromeos.looks_for_green.tests.test import ShouldLfgProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/json',
    'recipe_engine/properties',
    'gerrit',
    'git_footers',
    'looks_for_green',
]


PROPERTIES = ShouldLfgProperties

RELATED_OUTPUT = {
    'related': [{
        '_change_number': 123,
        '_revision_number': 1,
        'host': 'test-host',
        'project': 'sample'
    }, {
        '_change_number': 456,
        '_revision_number': 1,
        'host': 'test-host',
        'project': 'sample'
    }]
}


def RunSteps(api, properties):
  should_lfg = api.looks_for_green.should_lfg(
      api.buildbucket.build.input.gerrit_changes)
  api.assertions.assertEqual(properties.expected_should_lfg, should_lfg)
  api.looks_for_green.lookback_hours = 10
  api.assertions.assertEqual(10, api.looks_for_green.lookback_hours)


gerrit_change_1 = GerritChange(
    host='chromium-review.googlesource.com',
    change=1234,
    patchset=1,
)

gerrit_change_2 = GerritChange(
    host='chromium-review.googlesource.com',
    change=4568,
    patchset=1,
)

gerrit_change_3 = GerritChange(
    host='chromium-review.googlesource.com',
    change=9012,
    patchset=1,
)


def GenTests(api):

  yield api.test(
      'should-lfg',
      api.buildbucket.try_build(gerrit_changes=[gerrit_change_1]),
      api.properties(
          expected_should_lfg=True, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'lfg-disabled',
      api.properties(expected_should_lfg=False),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.post_check(
          post_process.DoesNotRun,
          'check should look for green.check disallow looks for green'),
      api.post_check(post_process.DoesNotRun,
                     'check should look for green.gerrit-fetch-changes'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'disallow-footer',
      api.buildbucket.try_build(gerrit_changes=[gerrit_change_1]),
      api.properties(
          expected_should_lfg=False, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.git_footers.simulated_get_footers(
          ['True'],
          'check should look for green.check disallow looks for green'),
      api.post_check(LooksStatusEquals,
                     LooksForGreenStatus.STATUS_SKIPPED_DISALLOW),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cq-depend-but-submitted',
      api.buildbucket.try_build(gerrit_changes=[gerrit_change_1]),
      api.properties(
          expected_should_lfg=True, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.git_footers.simulated_get_footers([
          'chromium:123456'
      ], 'check should look for green.check if all Cq-Depend CLs are included'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'depended-cls',
      api.buildbucket.try_build(gerrit_changes=[gerrit_change_1]),
      api.properties(
          expected_should_lfg=True, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.gerrit.set_gerrit_related_changes(
          RELATED_OUTPUT,
          step_name='check should look for green.find related CLs'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-submitted-depended-cls',
      api.buildbucket.try_build(
          gerrit_changes=[gerrit_change_1, gerrit_change_2]),
      api.properties(
          expected_should_lfg=False, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.gerrit.set_gerrit_related_changes(
          RELATED_OUTPUT,
          step_name='check should look for green.find related CLs'),
      api.step_data('check should look for green.gerrit changes',
                    api.json.output([])),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_FOUND_NONE),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-cq',
      api.properties(
          expected_should_lfg=False, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.post_check(post_process.StepTextEquals, 'check should look for green',
                     'Skipping looks for green outside of CQ'),
      api.post_process(post_process.DropExpectation),
  )
