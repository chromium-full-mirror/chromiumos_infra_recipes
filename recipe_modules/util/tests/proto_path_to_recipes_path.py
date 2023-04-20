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
    'use_sdk_path':
        Property(kind=bool, help='Whether to pass in the cros_sdk_path kwarg.'),
}


def RunSteps(api: recipe_api.RecipeApi, input_path: str,
             input_location: common_pb2.Path.Location,
             use_sdk_path: bool) -> None:
  proto_path = common_pb2.Path(path=input_path, location=input_location)
  sdk_path = api.cros_sdk.chroot_path if use_sdk_path else None
  with api.step.nest('convert path') as presentation:
    result = api.util.proto_path_to_recipes_path(proto_path, sdk_path)
    presentation.step_text = api.path.abspath(result)


def GenTests(api: recipe_test_api.RecipeTestApi):

  yield api.test(
      'inside-success',
      api.properties(input_path='/foo/bar.txt',
                     input_location=common_pb2.Path.Location.INSIDE,
                     use_sdk_path=True),
      api.post_check(post_process.StepTextEquals, 'convert path',
                     '[CACHE]/cros_chroot/chroot/foo/bar.txt'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'inside-relative-path',
      api.properties(input_path='foo/bar.txt',
                     input_location=common_pb2.Path.Location.INSIDE,
                     use_sdk_path=True),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Cannot convert inside path not relative to "/":.*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'inside-config-types-path',
      api.properties(input_path='[CACHE]/foo/bar.txt',
                     input_location=common_pb2.Path.Location.INSIDE,
                     use_sdk_path=True),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Cannot convert inside path not relative to "/":.*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'inside-no-sdk-path',
      api.properties(input_path='/foo/bar.txt',
                     input_location=common_pb2.Path.Location.INSIDE,
                     use_sdk_path=False),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Cannot convert inside path without chroot path:.*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'outside-success',
      api.properties(input_path='[CACHE]/foo/bar.txt',
                     input_location=common_pb2.Path.Location.OUTSIDE,
                     use_sdk_path=False),
      api.post_check(post_process.StepTextEquals, 'convert path',
                     '[CACHE]/foo/bar.txt'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'outside-relative',
      api.properties(input_path='foo/bar.txt',
                     input_location=common_pb2.Path.Location.OUTSIDE,
                     use_sdk_path=False),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'could not figure out a base path for .*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'outside-not-in-anchor-point',
      api.properties(input_path='/foo/bar.txt',
                     input_location=common_pb2.Path.Location.OUTSIDE,
                     use_sdk_path=False),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'could not figure out a base path for .*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'location-not-specified',
      api.properties(input_path='[CACHE]/foo/bar.txt',
                     input_location=common_pb2.Path.Location.NO_LOCATION,
                     use_sdk_path=True),
      api.post_check(post_process.StepException, 'convert path'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'Cannot process path with unspecified location:.*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
