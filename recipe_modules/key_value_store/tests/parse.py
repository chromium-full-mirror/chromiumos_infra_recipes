# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import collections
import json
from typing import Dict

from PB.recipe_modules.chromeos.key_value_store.tests.tests import \
  ParseProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'key_value_store',
]


PROPERTIES = ParseProperties


def RunSteps(api: RecipeApi, properties: ParseProperties):
  api.assertions.maxDiff = None
  expected_json: Dict[str, str] = json.loads(properties.expected_json_str)
  actual_json = api.key_value_store.parse_contents(properties.contents,
                                                   source='a cool file')
  api.assertions.assertEqual(expected_json, actual_json)


def GenTests(api: RecipeTestApi):
  yield api.test('empty-contents',
                 api.properties(
                     contents='',
                     expected_json_str='{}',
                 ), api.post_process(post_process.DropExpectation))

  expected_dict = collections.OrderedDict()
  expected_dict['my_key'] = 'my value'
  yield api.test(
      'simple-success',
      api.properties(
          contents="my_key='my value'",
          expected_json_str=json.dumps(expected_dict),
      ), api.post_process(post_process.DropExpectation))

  expected_dict = collections.OrderedDict()
  expected_dict['double_quotes'] = 'hey'
  expected_dict['single_quotes'] = 'hello'
  expected_dict['with_whitespace'] = 'hi      '
  expected_dict['with_internal_quote'] = 'punctuation (")!'
  expected_dict['multiline'] = "hello,'\nworld!"
  expected_dict['multiline_with_fakeout'] = (
      "hello,\nnot_a_real_keyval = 'psych'\nworld!")
  yield api.test(
      'complicated-success',
      api.properties(
          contents='''
# Ignorable comment.
double_quotes="hey"
single_quotes='hello'
   with_whitespace\t=   \t'hi      ' \t
with_internal_quote = "punctuation (")!"
multiline = "hello,'
world!"
multiline_with_fakeout = "hello,
not_a_real_keyval = 'psych'
world!"

''',
          expected_json_str=json.dumps(expected_dict),
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'line-without-equals',
      api.properties(
          contents='''my_key='my value'
Hey, how's it going?''',
          expected_json_str='{}',
      ),
      api.post_check(post_process.StepFailure,
                     'parse key-value store from a cool file'),
      api.post_check(post_process.SummaryMarkdown,
                     "Invalid line (no assignment): Hey, how's it going?"),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'unterminated-multiline-value',
      api.properties(
          contents='''my_key='hello,
w
o
r
l''',
          expected_json_str='{}',
      ),
      api.post_check(post_process.StepFailure,
                     'parse key-value store from a cool file'),
      api.post_check(post_process.SummaryMarkdownRE,
                     r'Unterminated value \(key=my_key\): .*'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'invalid-quote-char',
      api.properties(
          contents='my_key=`my value`',
          expected_json_str='{}',
      ),
      api.post_check(post_process.StepFailure,
                     'parse key-value store from a cool file'),
      api.post_check(post_process.SummaryMarkdown,
                     'Invalid line (bad quote char): my_key=`my value`'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
