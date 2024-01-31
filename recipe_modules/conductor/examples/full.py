# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

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
                                step_name='conductor collect',
                                initial_retry=True)
  api.assertions.assertEqual(bbids, [123, 457])

  api.assertions.assertEqual(api.conductor.collect_config(None), None)


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
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/conductor':
                  ConductorProperties(
                      enable_conductor=True, conductor_dryrun=True,
                      polling_interval_seconds=120,
                      collect_configs={'child builds': collect_config})
          }),
      api.conductor.set_collect_output([123, 457], report=TEST_REPORT),
      api.post_check(post_process.StepCommandContains, 'write input json',
                     [json_format.MessageToJson(collect_config)]),
      api.post_check(post_process.StepCommandContains, 'conductor collect',
                     ['collect', '--input_json']),
      api.post_check(post_process.StepCommandContains, 'conductor collect', [
          '--bbids', '123,456', '--polling_interval', '120', '--dryrun',
          '--initial_retry'
      ]),
      api.post_check(post_process.PropertyEquals, 'conductor_report',
                     {'child builds': TEST_REPORT}),
      api.post_process(post_process.DropExpectation),
  )
