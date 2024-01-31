# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.conductor import CollectConfig
from PB.chromiumos.conductor import RetryRule
from PB.recipe_modules.chromeos.conductor.conductor import ConductorProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'conductor',
]



def RunSteps(api: RecipeApi):
  bbids = api.conductor.collect('child builds', ['123', '456'],
                                step_name='conductor collect')
  api.assertions.assertEqual(bbids, [123, 456])


collect_config = CollectConfig(rules=[RetryRule(cutoff_seconds=1)])

TEST_REPORT = {
    'builders': {
        'adlrvp-release-main': {
            'builds': [{
                'bbid': 8792359518877252753,
                'status': 'SUCCESS',
                'retry': False
            }],
            'retry_count': 0
        },
    },
    'retry_count': 0
}


def GenTests(api: RecipeTestApi):
  # Conductor returns nonzero retcode AND fails to parse.
  yield api.test(
      'complete-failure',
      api.properties(
          **{
              '$chromeos/conductor':
                  ConductorProperties(
                      enable_conductor=True, polling_interval_seconds=120,
                      collect_configs={'child builds': collect_config})
          }),
      api.step_data('conductor collect', retcode=4),
      api.step_data('read conductor output.read output json',
                    api.file.read_text('{bad json')),
      api.post_check(post_process.StepFailure, 'conductor collect'),
      api.post_process(post_process.DropExpectation),
  )

  # Conductor returns no bbids.
  yield api.test(
      'no-bbids',
      api.properties(
          **{
              '$chromeos/conductor':
                  ConductorProperties(
                      enable_conductor=True, polling_interval_seconds=120,
                      collect_configs={'child builds': collect_config})
          }),
      api.step_data('conductor collect', retcode=0),
      api.conductor.set_collect_output([]),
      api.post_check(post_process.StepFailure, 'read conductor output'),
      api.post_process(post_process.DropExpectation),
  )
