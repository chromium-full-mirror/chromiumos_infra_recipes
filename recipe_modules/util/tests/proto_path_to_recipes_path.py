# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.util.tests.tests import \
  ProtoPathToRecipesPathProperties
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_sdk',
    'util',
]


PROPERTIES = ProtoPathToRecipesPathProperties


def RunSteps(api: recipe_api.RecipeApi,
             properties: ProtoPathToRecipesPathProperties) -> None:
  proto_path = common_pb2.Path(path=properties.input_path,
                               location=properties.input_location)
  with api.step.nest('convert path') as presentation:
    result = api.util.proto_path_to_recipes_path(proto_path)
    presentation.step_text = api.path.abspath(result)


def GenTests(api: recipe_test_api.RecipeTestApi):

  yield api.test(
      'inside-path',
      api.properties(input_path='/foo/bar.txt',
                     input_location=common_pb2.Path.Location.INSIDE),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r"Cannot convert INSIDE path\. See this function's "
          r'docstring for suggestions\. .*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'outside-success',
      api.properties(input_path='[CACHE]/foo/bar.txt',
                     input_location=common_pb2.Path.Location.OUTSIDE),
      api.post_check(post_process.StepTextEquals, 'convert path',
                     '[CACHE]/foo/bar.txt'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'outside-relative',
      api.properties(input_path='foo/bar.txt',
                     input_location=common_pb2.Path.Location.OUTSIDE),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'could not figure out a base path for .*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'outside-not-in-anchor-point',
      api.properties(input_path='/foo/bar.txt',
                     input_location=common_pb2.Path.Location.OUTSIDE),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'could not figure out a base path for .*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'location-not-specified',
      api.properties(input_path='[CACHE]/foo/bar.txt',
                     input_location=common_pb2.Path.Location.NO_LOCATION),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Cannot process path with unspecified location:.*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
