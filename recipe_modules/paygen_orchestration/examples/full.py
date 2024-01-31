# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import PB.chromiumos.common as common_pb2
from PB.recipe_modules.chromeos.paygen_orchestration.examples.test import TestPaygenProperties

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'paygen_orchestration',
]


PROPERTIES = TestPaygenProperties


def RunSteps(api: RecipeApi, properties: TestPaygenProperties):
  api.assertions.assertEqual(
      len(
          api.paygen_orchestration.get_builder_configs(
              builder_name=properties.builder_name,
              delta_type=properties.delta_type)), properties.expected_length)

  api.assertions.assertEqual(api.paygen_orchestration.default_delta_types, [
      common_pb2.STEPPING_STONE, common_pb2.OMAHA, common_pb2.NO_DELTA,
      common_pb2.MILESTONE, common_pb2.FSI
  ])


def GenTests(api: RecipeTestApi):
  good_json, bad_json, not_json = map(
      api.paygen_orchestration.test_paygen, ['get paygen json.gsutil cat'] *
      len(api.paygen_orchestration.ALL_EXAMPLE_JSONS),
      api.paygen_orchestration.ALL_EXAMPLE_JSONS)

  build_message = api.buildbucket.ci_build_message(
      project='chromeos', bucket='release', builder='paygen-orchestrator')

  yield api.test(
      'basic', good_json,
      api.properties(builder_name='coral', delta_type='OMAHA',
                     expected_length=2), api.buildbucket.build(build_message))

  yield api.test(
      'basic-miss', good_json,
      api.properties(builder_name='videogamething', expected_length=0),
      api.buildbucket.build(build_message))

  yield api.test(
      'basic-delta-miss', good_json,
      api.properties(builder_name='amenia', expected_length=0,
                     delta_type='STEPPING_STONE'),
      api.buildbucket.build(build_message))

  yield api.test(
      'basic-hit', good_json,
      api.properties(builder_name='amenia',
                     expected_length=1, delta_type='NO_DELTA'),
      api.buildbucket.build(build_message))

  yield api.test('bad-json', api.buildbucket.build(build_message), bad_json,
                 status='FAILURE')
  yield api.test('not-json', api.buildbucket.build(build_message), not_json,
                 status='FAILURE')
