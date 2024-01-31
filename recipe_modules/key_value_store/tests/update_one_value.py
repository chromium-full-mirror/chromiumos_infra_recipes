# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.key_value_store.tests.tests import \
  UpdateOneValueProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'key_value_store',
]


PROPERTIES = UpdateOneValueProperties


def RunSteps(api: RecipeApi, properties: UpdateOneValueProperties):
  actual_new_contents = api.key_value_store.update_one_value(
      properties.original_contents, properties.key, properties.new_value,
      append_if_missing=properties.append_if_missing)
  api.assertions.assertEqual(properties.expected_new_contents,
                             actual_new_contents)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          original_contents='# A comment!\nmy_key="Old"',
          key='my_key',
          new_value='New',
          expected_new_contents='# A comment!\nmy_key="New"',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-whitespace',
      api.properties(original_contents='   my_key  \t=\t "Old"', key='my_key',
                     new_value='New', expected_new_contents='my_key="New"'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'value-ends-in-double-quote',
      api.properties(
          original_contents='punctuation_time="This is a comma: ,"',
          key='punctuation_time', new_value='This is a quotation mark: "',
          expected_new_contents='punctuation_time=\'This is a quotation mark: "\''
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'value-wrapped-in-mismatched-quotes',
      api.properties(
          original_contents='my_key="Old"',
          key='my_key',
          new_value='"Why would anybody do this?\'',
      ),
      api.post_check(post_process.StepException,
                     'update my_key in key-value store'),
      api.post_check(
          post_process.ResultReason,
          'New value "Why would anybody do this?\' is wrapped in mismatched quotes'
      ),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'key-occurs-multiple-times',
      api.properties(
          original_contents='my_key="One"\nyour_key="Two"\nmy_key=\'Three\'',
          key='my_key',
          new_value='Four',
      ),
      api.post_check(post_process.StepFailure,
                     'update my_key in key-value store'),
      api.post_check(post_process.ResultReasonRE,
                     'Found key my_key multiple times in key-value store:.*'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'missing-and-append',
      api.properties(
          original_contents='present_key="One"',
          key='missing_key',
          new_value='Two',
          append_if_missing=True,
          expected_new_contents='present_key="One"\n\nmissing_key="Two"',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'missing-and-do-not-append',
      api.properties(
          original_contents='present_key="One"',
          key='missing_key',
          new_value='Two',
      ),
      api.post_check(post_process.StepFailure,
                     'update missing_key in key-value store'),
      api.post_check(post_process.ResultReasonRE,
                     'Key-value store missing missing_key:.*'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'old-value-is-multiline',
      api.properties(
          original_contents='my_key="Hello...\n...world!"',
          key='my_key',
          new_value='Hello, world!',
      ),
      api.post_check(post_process.StepException,
                     'update my_key in key-value store'),
      api.post_check(post_process.ResultReasonRE,
                     'Found multiline value for my_key in key-value store:.*'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
