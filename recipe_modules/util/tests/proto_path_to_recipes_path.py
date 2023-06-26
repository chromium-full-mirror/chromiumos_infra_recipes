# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos import common as common_pb2
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_sdk',
    'util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'input_path':
        Property(kind=str, help='The path to use in the input proto path.'),
    'input_location':
        Property(kind=int, help='The location to use in the input proto path.'),
}


def RunSteps(api: recipe_api.RecipeApi, input_path: str,
             input_location: common_pb2.Path.Location) -> None:
  proto_path = common_pb2.Path(path=input_path, location=input_location)
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
