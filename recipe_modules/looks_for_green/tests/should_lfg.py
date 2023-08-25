# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from RECIPE_MODULES.chromeos.looks_for_green.test_utils import LooksStatusEquals

from PB.chromiumos.common import GerritChange
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus
from PB.recipe_modules.chromeos.looks_for_green.tests.test import ShouldLfgProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'gerrit',
    'git_footers',
    'looks_for_green',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ShouldLfgProperties

one_gerrit_change = [
    GerritChange(
        host='chromium-review.googlesource.com',
        change=1234,
    )
]
multiple_gerrit_changes = [
    GerritChange(
        host='chromium-review.googlesource.com',
        change=1234,
    ),
    GerritChange(
        host='chromium-review.googlesource.com',
        change=5678,
    ),
    GerritChange(
        host='chromium-review.googlesource.com',
        change=9012,
    )
]


def RunSteps(api, properties):
  if properties.enable_test_on_multiple_changes:
    gerrit_changes = multiple_gerrit_changes
  else:
    gerrit_changes = one_gerrit_change
  should_lfg = api.looks_for_green.should_lfg(properties.experiments,
                                              gerrit_changes)
  api.assertions.assertEqual(properties.expected_should_lfg, should_lfg)


def GenTests(api):
  lfg_experiment = {'chromeos.cros_infra_config.cq_looks': True}

  yield api.test(
      'should-lfg',
      api.properties(
          expected_should_lfg=True, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
      api.step_data('check should look for green.git log',
                    api.raw_io.stream_output_text('commitsha1')),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check if CL uses Cq-Depend'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-experiment',
      api.properties(
          expected_should_lfg=False, experiments={}, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.post_check(
          post_process.DoesNotRun,
          'check should look for green.check disallow looks for green'),
      api.post_check(post_process.DoesNotRun,
                     'check should look for green.gerrit-fetch-changes'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'lfg-disabled',
      api.properties(experiments=lfg_experiment, expected_should_lfg=False),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.post_check(
          post_process.DoesNotRun,
          'check should look for green.check disallow looks for green'),
      api.post_check(post_process.DoesNotRun,
                     'check should look for green.gerrit-fetch-changes'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'disallow-footer',
      api.properties(
          expected_should_lfg=False, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.git_footers.simulated_get_footers(
          ['True'],
          'check should look for green.check disallow looks for green'),
      api.post_check(LooksStatusEquals,
                     LooksForGreenStatus.STATUS_SKIPPED_DISALLOW),
      api.post_process(post_process.DropExpectation),
  )

  # TODO(b/276363760): Remove when Cq-Depended changes are supported.
  yield api.test(
      'cq-depend',
      api.properties(
          expected_should_lfg=False, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
      api.git_footers.simulated_get_footers(
          ['123456'], 'check should look for green.check if CL uses Cq-Depend'),
      api.post_check(LooksStatusEquals,
                     LooksForGreenStatus.STATUS_SKIPPED_CQ_DEPEND),
      api.post_process(post_process.DropExpectation),
  )

  # TODO(b/276363760): Remove when relation chains are supported.
  related_output = {
      'related': [{
          '_change_number': '1234'
      }, {
          '_change_number': '4321'
      }]
  }
  yield api.test(
      'relation-chain',
      api.properties(
          expected_should_lfg=False, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
      api.step_data('check should look for green.git log',
                    api.raw_io.stream_output_text('commitsha1')),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check if CL uses Cq-Depend'),
      api.gerrit.set_gerrit_related_changes(
          related_output,
          'check should look for green.check if CL has related changes.Check for stacked change'
      ),
      api.post_check(LooksStatusEquals,
                     LooksForGreenStatus.STATUS_SKIPPED_STACKED_CHANGES),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'merge-commit',
      api.properties(
          expected_should_lfg=False, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
      api.step_data('check should look for green.git log',
                    api.raw_io.stream_output_text('commitsha1 commitsha2')),
      api.post_check(LooksStatusEquals,
                     LooksForGreenStatus.STATUS_SKIPPED_MERGE_COMMIT),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cherry-pick-and-merge-commits',
      api.properties(
          expected_should_lfg=False, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }, enable_test_on_multiple_changes=True),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green',
          step_number=2),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check should look for green', multiple_gerrit_changes, {
              1234: {},
              4568: {},
              9012: {},
          }),
      # Cherry pick commit (one ancestor)
      api.step_data('check should look for green.git log',
                    api.raw_io.stream_output_text('commitsha1')),
      # Merge commit (multiple ancestors)
      api.step_data('check should look for green.git log (2)',
                    api.raw_io.stream_output_text('commitsha1 commitsha2')),
      api.post_check(LooksStatusEquals,
                     LooksForGreenStatus.STATUS_SKIPPED_MERGE_COMMIT),
      # Should not continue after finding a merge commit.
      api.post_check(post_process.DoesNotRun,
                     'check should look for green.git log (3)'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-cq',
      api.properties(
          expected_should_lfg=False, experiments=lfg_experiment, **{
              '$chromeos/looks_for_green': {
                  'enable_looks_for_green': True
              },
          }),
      api.post_check(post_process.StepTextEquals, 'check should look for green',
                     'Skipping looks for green outside of CQ'),
      api.post_process(post_process.DropExpectation),
  )
