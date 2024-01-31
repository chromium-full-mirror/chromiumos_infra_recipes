# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipes.chromeos.paygen import PaygenProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'conductor',
    'paygen_orchestration',
]



def RunSteps(api: RecipeApi):
  # Test 201 gen requests (higher than bb.schedule's chunk size max of 200).
  gen_requests = api.paygen_orchestration.test_api.EXAMPLE_GEN_REQUESTS * 201

  paygen_requests = [
      PaygenProperties.PaygenRequest(generation_request=gen_request)
      for gen_request in gen_requests
  ]

  paygen_mpa = api.properties.thaw()['paygen_mpa']
  api.paygen_orchestration.run_paygen_builders(paygen_requests,
                                               paygen_mpa=paygen_mpa,
                                               use_split_paygen=True)


test_bbids = [str(8922054662172514000 + i) for i in range(805)]


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic', api.properties(paygen_mpa=False),
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'request', ['"use_split_paygen": true']),
      api.buildbucket.build(
          api.buildbucket.ci_build_message(project='chromeos', bucket='release',
                                           builder='paygen-orchestrator')),
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'json.output', ['\"bucket\": \"release\"']),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'basic-try-build', api.properties(paygen_mpa=False),
      api.buildbucket.build(
          api.buildbucket.ci_build_message(project='chromeos', bucket='try-dev',
                                           builder='paygen-orchestrator')),
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'json.output', ['\"bucket\": \"try-dev\"']),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'basic-led-real-build', api.properties(paygen_mpa=False),
      api.buildbucket.build(
          api.buildbucket.ci_build_message(project='chromeos',
                                           bucket='staging.shadow',
                                           builder='paygen-orchestrator')),
      api.properties(**{'$recipe_engine/led': {
          'shadowed_bucket': 'staging',
      }}),
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'json.output', ['\"bucket\": \"staging\"']),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'conductor-no-retries', api.properties(paygen_mpa=False),
      api.properties(
          **{
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'paygen': {},
                  },
              },
          }),
      api.conductor.set_collect_output(test_bbids,
                                       step_name='running children'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'conductor-retries',
      api.properties(paygen_mpa=False),
      api.properties(
          **{
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'paygen': {},
                  },
              },
          }),
      # Don't return one of the original builds (8922054662172514000).
      api.conductor.set_collect_output(
          [str(8922054662172514001 + i) for i in range(804)],
          step_name='running children'),
      api.post_process(post_process.DropExpectation))

  # TODO(b/305046854): Temporarily allow MPA bot pool overrides.
  yield api.test(
      'mpa', api.properties(paygen_mpa=True),
      api.buildbucket.build(
          api.buildbucket.ci_build_message(project='chromeos', bucket='release',
                                           builder='paygen-orchestrator-mpa')),
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'request', ['"builder": "paygen-mpa"']),
      api.post_process(post_process.DropExpectation))
