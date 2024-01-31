# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.wrappers_pb2 import Int32Value

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'easy',
]



def RunSteps(api: RecipeApi):
  api.easy.step('passthru', ['cat'], ok_ret=(0, 1))

  stdout = api.easy.stdout_step('raw', ['gzip'], stdin_data='uncompressed',
                                test_stdout=lambda: 'compressed')
  api.assertions.assertEqual(stdout, b'compressed')

  proto_out = api.easy.stdout_jsonpb_step('jsonpb', ['foo'], Int32Value,
                                          test_output=Int32Value(value=1))
  api.assertions.assertIsInstance(proto_out, Int32Value)
  api.assertions.assertEqual(proto_out.value, 1)

  json_stdout = api.easy.stdout_json_step('json', ['jq'], stdin_json={'a': 1},
                                          test_stdout={'b': 2})
  api.assertions.assertDictEqual(json_stdout, {'b': 2})
  api.easy.set_properties_step(my_property='value')
  api.easy.set_properties_step(property1='value1', property2='value2')
  api.easy.set_properties_step(property1=b'my_bytes', property2=[b'your_bytes'])


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
