# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.chromiumos.common import GerritChange
from PB.recipe_modules.chromeos.looks_for_green.tests.test import ShouldLfgProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'git_footers',
    'looks_for_green',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ShouldLfgProperties


def RunSteps(api, properties):
  gerrit_changes = [
      GerritChange(
          host="chromium-review.googlesource.com",
          change=1234,
      )
  ]
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
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
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
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'lfg-disabled',
      api.properties(experiments=lfg_experiment, expected_should_lfg=False),
      api.git_footers.simulated_get_footers(
          [], 'check should look for green.check disallow looks for green'),
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
      api.git_footers.simulated_get_footers(
          ['True'],
          'check should look for green.check disallow looks for green'),
      api.post_process(post_process.DropExpectation),
  )
